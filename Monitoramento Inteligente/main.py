# =============================================================================
# main.py
# -------
# PONTO DE ENTRADA do módulo GENÉRICO "Monitoramento Inteligente".
#
# Fluxo:
#   1. Carrega a DEMANDA (demanda.json) — injeta cliente, palavras-chave,
#      veículos, contexto, exclusões e caminhos de entrega no config.
#   2. Define a janela (--de/--ate da CLI ou as datas da própria demanda).
#   3. ScraperEngine coleta (RSS + Lupa + Google News) na janela EXATA.
#   4. Pré-filtro rápido (título+resumo) e avaliação semântica do full-text.
#   5. Encurtamento dos links e exportação .docx (formato WhatsApp) por cliente.
#   6. Manifesto .csv + arquivamento de relatórios antigos.
#
# Execução:
#   python main.py --demanda "C:\...\demanda.json"
#   python main.py                              # usa o demanda.json da pasta
# =============================================================================

import argparse
import csv
import datetime
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import config
import demanda
from scraper import ScraperEngine
from semantic_filter import SemanticFilter
from link_shortener import LinkShortener
from word_exporter import WordExporter
import saude

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


# -----------------------------------------------------------------------------
# LOGGING EM ARQUIVO (com rotação — 1 log por execução)
# -----------------------------------------------------------------------------
def _rotacionar_log():
    try:
        if not os.path.exists(config.ARQUIVO_LOG):
            return
        os.makedirs(config.DIR_LOGS, exist_ok=True)
        agora = config.agora_brasilia()
        destino = os.path.join(
            config.DIR_LOGS,
            f"execucao_{agora:%Y-%m-%d_%Hh%M}.log",
        )
        if os.path.exists(destino):
            if os.path.getsize(destino) == 0:
                os.remove(destino)
            else:
                destino = os.path.join(
                    config.DIR_LOGS,
                    f"execucao_{agora:%Y-%m-%d_%Hh%M%S}s.log",
                )
        os.rename(config.ARQUIVO_LOG, destino)
        arquivados = sorted(
            (
                os.path.join(config.DIR_LOGS, nome)
                for nome in os.listdir(config.DIR_LOGS)
                if nome.startswith("execucao_") and nome.endswith(".log")
            ),
            key=os.path.getmtime,
            reverse=True,
        )
        for obsoleto in arquivados[config.MAX_LOGS_ARQUIVADOS:]:
            try:
                os.remove(obsoleto)
            except OSError:
                pass
        logger.info("Log anterior rotacionado: %s", destino)
    except OSError as exc:
        logger.warning("Falha ao rotacionar o log: %s", exc)


def _configurar_log_em_arquivo():
    """Adiciona o handler de arquivo ao logging (caminhos já apontam para a
    pasta do cliente da demanda)."""
    try:
        _rotacionar_log()
        os.makedirs(config.DIR_LOGS, exist_ok=True)
        handler = logging.FileHandler(config.ARQUIVO_LOG, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logging.getLogger().addHandler(handler)
    except OSError as exc:
        logger.warning("Não foi possível configurar o log em arquivo: %s", exc)


# -----------------------------------------------------------------------------
# CLI — DEMANDA + JANELA (horas ou intervalo de datas)
# -----------------------------------------------------------------------------
def _parsear_data_cli(valor):
    try:
        return datetime.datetime.strptime(valor.strip(), "%d/%m/%Y")
    except (ValueError, AttributeError):
        return None


def _janela_calendario(de, ate, nao_arquivar, sem_cache, rotulo):
    """Monta a janela calendário [inicio, fim] e devolve o dict do pipeline."""
    agora = config.agora_brasilia()
    data_inicio = datetime.datetime(de.year, de.month, de.day)
    data_fim = datetime.datetime(ate.year, ate.month, ate.day, 23, 59, 59)
    if data_inicio > data_fim:
        raise ValueError("A data inicial deve ser anterior ou igual à data final.")
    if data_inicio > agora:
        raise ValueError("A data inicial está no futuro.")
    if data_fim > agora:
        data_fim = agora
    horas = max(1, int((agora - data_inicio).total_seconds() // 3600) + 1)
    return {
        "horas": horas,
        "data_limite": data_inicio,
        "data_limite_max": data_fim,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "rotulo": rotulo,
        "arquivar": not nao_arquivar,
        "sem_cache": sem_cache,
    }


def _janela_horas(horas, nao_arquivar, sem_cache):
    return {
        "horas": horas,
        "data_limite": None,
        "data_limite_max": None,
        "data_inicio": None,
        "data_fim": None,
        "rotulo": f"{horas} horas",
        "arquivar": not nao_arquivar,
        "sem_cache": sem_cache,
    }


def ler_argumentos():
    parser = argparse.ArgumentParser(
        description="Monitoramento Inteligente — Motor de Busca e Clipping Genérico"
    )
    parser.add_argument(
        "--demanda",
        type=str,
        default=None,
        help="Caminho do demanda.json (padrão: demandas/demanda.json desta pasta).",
    )
    parser.add_argument(
        "--horas", type=int, default=None,
        help="Últimas N horas (ignora as datas da demanda se informado).",
    )
    parser.add_argument(
        "--de", type=str, default=None,
        help="Data inicial (DD/MM/AAAA). Use com --ate.",
    )
    parser.add_argument(
        "--ate", type=str, default=None,
        help="Data final (DD/MM/AAAA). Use com --de.",
    )
    parser.add_argument(
        "--nao-arquivar", action="store_true",
        help="NÃO mover relatórios antigos para a pasta Arquivo.",
    )
    parser.add_argument(
        "--sem-cache", action="store_true", default=False,
        help="Ignora o cache persistente de full-text.",
    )
    return parser.parse_args()


# -----------------------------------------------------------------------------
# PRÉ-FILTRO RÁPIDO (Título + Resumo)
# -----------------------------------------------------------------------------
def pre_filtrar_rapido(noticias, filtro):
    """
    Descarta na hora matérias claramente fora do tema (sem nenhum sinal de
    cliente, keyword, chave forte ou contexto). A decisão FINAL é do full-text.
    """
    candidatas = []
    for noticia in noticias:
        veiculo = noticia.get("veiculo", "")
        texto_pre = f"{noticia['titulo']} {noticia['resumo']}"
        normalizado_pre = filtro._normalizar(texto_pre)

        # Blacklist global (ruído transversal) já fura o título/resumo.
        if filtro._nivel4_blacklist(normalizado_pre):
            logger.debug(
                "Pré-filtro descartou (exclusão): %s", noticia["titulo"][:60]
            )
            continue

        if filtro._pre_tem_sinal(normalizado_pre):
            candidatas.append(noticia)

    logger.info(
        "Pré-filtro: %d notícia(s) mantida(s) de %d (descarte rápido).",
        len(candidatas),
        len(noticias),
    )
    return candidatas


# -----------------------------------------------------------------------------
# AVALIAÇÃO INDIVIDUAL DE UMA CANDIDATA (full-text + matriz semântica)
# -----------------------------------------------------------------------------
def avaliar_candidata(motor_engine, filtro, noticia):
    """
    Busca full-text + data de PUBLICAÇÃO ORIGINAL no HTML, valida a janela
    EXATA (nada além dela) e aplica a matriz N1/N2/N4.

    Regra de engenharia (sempre conferir no site): a janela considera só a
    data de publicação ORIGINAL (article:published_time / datePublished).
    Matéria publicada ANTES do recorte e apenas ATUALIZADA dentro dele é
    descartada. Publicada DENTRO do recorte (atualizada dentro ou fora) é
    mantida. A data de atualização NUNCA decide.
    """
    texto_completo, data_pub_html, url_final = motor_engine._obter_texto_e_data(
        noticia["link"]
    )

    sobra_para_baixo = (
        data_pub_html is not None and data_pub_html < motor_engine.data_limite
    )
    sobra_para_cima = (
        data_pub_html is not None
        and motor_engine.data_limite_max is not None
        and data_pub_html > motor_engine.data_limite_max
    )
    if sobra_para_baixo or sobra_para_cima:
        return ("data_fora", noticia)

    if data_pub_html is None and noticia.get("data_publicacao") is None:
        return ("sem_data", noticia)

    if data_pub_html is not None:
        noticia["data_publicacao"] = data_pub_html

    noticia["link"] = url_final

    if not texto_completo.strip():
        texto_avaliado = f"{noticia['titulo']} {noticia['resumo']}"
    else:
        texto_avaliado = texto_completo

    superficie = f"{noticia['titulo']} {noticia.get('resumo', '')}"

    noticia["full_text"] = texto_completo
    noticia["texto_avaliado"] = texto_avaliado

    is_relevante, clientes_citados = filtro.avaliar(texto_avaliado, superficie)
    noticia["is_relevante"] = is_relevante
    noticia["clientes_citados"] = clientes_citados

    if is_relevante:
        return ("aprovada", noticia)
    return ("reprovada", noticia)


# -----------------------------------------------------------------------------
# PIPELINE PRINCIPAL
# -----------------------------------------------------------------------------
def executar_pipeline(janela, info_demanda):
    inicio = time.time()
    horas_passadas = janela["horas"]

    logger.info("=" * 70)
    logger.info(
        "MONTAR DEMANDA — %s (%s)",
        info_demanda["cliente"],
        info_demanda["cliente_slug"],
    )
    logger.info("Janela EXATA: %s", janela["rotulo"])
    logger.info(
        "Veículos (%d): %s",
        len(config.VEICULOS),
        ", ".join(list(config.VEICULOS)),
    )
    logger.info(
        "Destacar clipping: %s | Palavras-chave: %d | Contexto: %d | Exclusão: %d",
        info_demanda["destacar_clipping"],
        len(config.PALAVRAS_CHAVE),
        len(config.TERMOS_CONTEXTO),
        len(config.TERMOS_EXCLUSAO),
    )
    logger.info("=" * 70)

    # ---- 1. COLETA ----
    motor = ScraperEngine(
        horas_passadas=horas_passadas,
        data_limite_max=janela.get("data_limite_max"),
        data_limite=janela.get("data_limite"),
        sem_cache=janela.get("sem_cache", False),
    )
    todas_as_noticias = motor.coletar_todos()

    # ---- SAÚDE DOS FEEDS ----
    historico_saude = saude.carregar_historico()
    historico_saude = saude.registrar_run(historico_saude, motor, janela["rotulo"])
    for alerta_saude in saude.verificar_alertas(historico_saude):
        logger.warning(alerta_saude)
    saude.salvar_historico(historico_saude)

    if not todas_as_noticias:
        logger.warning("Nenhuma notícia coletada. Nada a gerar.")
        return None

    # ---- 2. PRÉ-FILTRO ----
    filtro = SemanticFilter()
    candidatas = pre_filtrar_rapido(todas_as_noticias, filtro)
    if not candidatas:
        logger.warning("Nenhuma notícia aprovou o pré-filtro. Nada a gerar.")
        return None

    # ---- 3. AVALIAÇÃO SEMÂNTICA (full-text) em paralelo ----
    logger.info("Analisando full-text e aplicando matriz semântica...")
    aprovadas = []
    descartadas_por_data = 0
    sem_data = 0
    reprovadas = 0
    com_fulltext = 0

    with ThreadPoolExecutor(max_workers=config.ANALISE_WORKERS) as executor:
        for status, noticia in executor.map(
            lambda n: avaliar_candidata(motor, filtro, n), candidatas
        ):
            if (noticia.get("full_text") or "").strip():
                com_fulltext += 1
            if status == "aprovada":
                aprovadas.append(noticia)
            elif status == "data_fora":
                descartadas_por_data += 1
            elif status == "sem_data":
                sem_data += 1
            else:
                reprovadas += 1

    if descartadas_por_data:
        logger.info(
            "%d notícia(s) descartada(s): publicação ORIGINAL fora da janela "
            "exata (%s).",
            descartadas_por_data,
            janela["rotulo"],
        )

    motor._salvar_cache()

    # ---- Ordenação: clipping (cliente citado) no topo quando destacar ----
    if info_demanda["destacar_clipping"]:
        aprovadas.sort(
            key=lambda n: (
                1 if (n.get("clientes_citados") or []) else 0,
                n.get("data_publicacao") or _data_fallback(),
            ),
            reverse=True,
        )
    else:
        aprovadas.sort(
            key=lambda n: n.get("data_publicacao") or _data_fallback(),
            reverse=True,
        )

    logger.info(
        "Matriz semântica: %d notícia(s) APROVADA(s) de %d candidata(s).",
        len(aprovadas),
        len(candidatas),
    )
    if not aprovadas:
        logger.warning("Nenhuma notícia relevante encontrada. Nada a gerar.")
        return None

    # ---- 4. ENCURTAMENTO E VALIDAÇÃO DE LINKS ----
    logger.info("Encurtando e validando %d link(s)...", len(aprovadas))
    encurtador = LinkShortener()
    for noticia in aprovadas:
        link = noticia["link"]
        if motor._eh_link_google_news(link):
            canonica = motor._resolver_url_google_news(link)
            if canonica:
                link = canonica
                noticia["link"] = canonica
        noticia["link_encurtado"] = encurtador.encurtar(link)

    # ---- 5. EXPORTAÇÃO .docx + MANIFESTO .csv + ARQUIVAMENTO ----
    logger.info("Gerando relatório Word...")
    exportador = WordExporter()
    caminho_arquivo = exportador.exportar(
        aprovadas,
        horas_passadas=horas_passadas,
        data_inicio=janela.get("data_inicio"),
        data_fim=janela.get("data_fim"),
        quantidade_materias=len(aprovadas),
        cliente_slug=info_demanda["cliente_slug"],
    )
    _salvar_manifesto_csv(caminho_arquivo, aprovadas)
    if janela.get("arquivar"):
        _arquivar_relatorios_antigos(caminho_arquivo)

    duracao = time.time() - inicio
    logger.info("=" * 70)
    logger.info("MÉTRICAS DA EXECUÇÃO (janela: %s):", janela["rotulo"])
    logger.info("  • %d matéria(s) coletada(s) (bruto).", len(todas_as_noticias))
    logger.info(
        "  • %d matéria(s) avaliada(s) no full-text — %d com texto completo.",
        len(aprovadas) + reprovadas,
        com_fulltext,
    )
    logger.info("  • %d matéria(s) APROVADA(s) e salvas no .docx.", len(aprovadas))
    if sem_data or descartadas_por_data:
        logger.info(
            "  • descartadas: %d por data fora da janela; %d sem data de publicação.",
            descartadas_por_data,
            sem_data,
        )
    logger.info("=" * 70)
    logger.info("Arquivo salvo em: %s", caminho_arquivo)
    logger.info("Tempo total: %.1f segundos.", duracao)
    logger.info("=" * 70)
    return caminho_arquivo


# -----------------------------------------------------------------------------
# MANIFESTO CSV (rastreabilidade)
# -----------------------------------------------------------------------------
def _salvar_manifesto_csv(caminho_docx, aprovadas):
    caminho_csv = os.path.splitext(caminho_docx)[0] + ".csv"
    try:
        with open(caminho_csv, "w", encoding="utf-8-sig", newline="") as arquivo:
            gravador = csv.writer(arquivo, delimiter=";")
            gravador.writerow(
                [
                    "veiculo",
                    "titulo",
                    "clientes_citados",
                    "data_publicacao",
                    "link_curto",
                    "link_original",
                    "origem",
                ]
            )
            for noticia in aprovadas:
                data_pub = noticia.get("data_publicacao")
                gravador.writerow(
                    [
                        noticia.get("veiculo", ""),
                        noticia.get("titulo", ""),
                        "; ".join(noticia.get("clientes_citados") or []),
                        data_pub.strftime("%Y-%m-%d %H:%M") if data_pub else "",
                        noticia.get("link_encurtado", ""),
                        noticia.get("link", ""),
                        noticia.get("origem", ""),
                    ]
                )
        logger.info("Manifesto CSV salvo: %s", caminho_csv)
    except OSError as exc:
        logger.warning("Não foi possível salvar o manifesto CSV: %s", exc)
    return caminho_csv


# -----------------------------------------------------------------------------
# ARQUIVAMENTO DOS RELATÓRIOS ANTERIORES
# -----------------------------------------------------------------------------
def _arquivar_relatorios_antigos(caminho_atual):
    try:
        os.makedirs(config.DIR_ARQUIVO, exist_ok=True)
        base_atual = os.path.splitext(caminho_atual)[0]
        movidos = 0
        for nome in os.listdir(config.DIR_RELATORIOS):
            origem = os.path.join(config.DIR_RELATORIOS, nome)
            if not os.path.isfile(origem):
                continue
            if not (nome.lower().endswith(".docx") or nome.lower().endswith(".csv")):
                continue
            if os.path.abspath(origem).startswith(os.path.abspath(base_atual)):
                continue
            os.replace(origem, os.path.join(config.DIR_ARQUIVO, nome))
            movidos += 1
        if movidos:
            logger.info(
                "%d relatório(s) anterior(es) arquivado(s) em: %s",
                movidos,
                config.DIR_ARQUIVO,
            )
    except OSError as exc:
        logger.warning("Falha ao arquivar relatórios antigos: %s", exc)


def _data_fallback():
    return datetime.datetime(1970, 1, 1)


# -----------------------------------------------------------------------------
# BLOCO PRINCIPAL
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    argumentos = ler_argumentos()

    # 1) Carrega a DEMANDA e aponta os caminhos para a pasta do cliente.
    caminho_demanda = argumentos.demanda or demanda.caminho_demanda_padrao()
    if not os.path.isfile(caminho_demanda):
        logger.error(
            "Demanda não encontrada: %s (passe --demanda <arquivo>).",
            caminho_demanda,
        )
        raise SystemExit(1)
    info_demanda = demanda.carregar(caminho_demanda)
    logger.info(
        "Demanda carregada: %s (pasta %s)",
        info_demanda["cliente"],
        config.BASE_DIR,
    )

    # 2) Log em arquivo SÓ DEPOIS que os caminhos do cliente existem.
    _configurar_log_em_arquivo()

    # 3) Janela: CLI (--de/--ate ou --horas) tem prioridade; senão, usa as
    #    datas EXATAS da demanda.
    if argumentos.de or argumentos.ate:
        de = _parsear_data_cli(argumentos.de)
        ate = _parsear_data_cli(argumentos.ate)
        if de is None or ate is None:
            logger.error("Datas inválidas. Use DD/MM/AAAA.")
            raise SystemExit(1)
        janela = _janela_calendario(
            de,
            ate,
            nao_arquivar=argumentos.nao_arquivar,
            sem_cache=argumentos.sem_cache,
            rotulo=f"{argumentos.de} a {argumentos.ate}",
        )
    elif argumentos.horas and argumentos.horas > 0:
        janela = _janela_horas(
            argumentos.horas,
            nao_arquivar=argumentos.nao_arquivar,
            sem_cache=argumentos.sem_cache,
        )
    else:
        janela = _janela_calendario(
            info_demanda["data_inicio"],
            info_demanda["data_fim"],
            nao_arquivar=argumentos.nao_arquivar,
            sem_cache=argumentos.sem_cache,
            rotulo=(
                f"{info_demanda['data_inicio']:%d/%m/%Y} a "
                f"{info_demanda['data_fim']:%d/%m/%Y}"
            ),
        )

    caminho = executar_pipeline(janela, info_demanda)
    if caminho:
        logger.info("Concluído! Abra o arquivo: %s", caminho)
    else:
        logger.info("Nenhum relatório foi gerado nesta execução.")