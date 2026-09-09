# =============================================================================
# main.py
# -------
# PONTO DE ENTRADA do "Motor de Busca e Clipping de Notícias do Setor Elétrico".
#
# Fluxo completo (pipeline):
#   1.  CLI interativo: pergunta quantas horas passadas devem ser varridas.
#   2.  ScraperEngine coleta as notícias dos 18 veículos (via RSS com
#       enriquecimento de full-text).
#   3.  Pré-filtro RÁPIDO: usa título + resumo do RSS para descartar matérias
#       claramente irrelevantes, evitando baixar full-text á toa.
#   4.  SemanticFilter aplica a matriz NLP (Níveis 1 a 4) sobre o full-text.
#   5.  LinkShortener encurta e valida os links aprovados (IS.GD + failover).
#   6.  WordExporter gera o .docx final com a formatação do WhatsApp.
#
# Execução: python main.py
# =============================================================================

import argparse
import csv
import datetime
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

import config
from scraper import ScraperEngine
from semantic_filter import SemanticFilter
from link_shortener import LinkShortener
from word_exporter import WordExporter
import saude

# Configuração do logging (console + arquivo em Logs\execucao.log).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


# -----------------------------------------------------------------------------
# LOGGING EM ARQUIVO (organizado em Logs\execucao.log, com ROTAÇÃO)
# -----------------------------------------------------------------------------
def _rotacionar_log():
    """
    Rotação simples: no início de cada execução, o execucao.log atual é
    renomeado para execucao_<data>_<hora>.log (resultado: um arquivo de log
    por execução). Mantém no máximo config.MAX_LOGS_ARQUIVADOS arquivos na
    pasta de Logs, removendo os mais antigos — o log nunca cresce sem limite.

    Proteções contra perda de dados:
      - Se o destino já existir e for NÃO-vazio (outra execução no mesmo
        minuto), usa sufixo com segundos em vez de sobrescrever.
      - Nunca apaga um arquivo de log com conteúdo.
    """
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
                os.remove(destino)  # Vazio (aberto e fechado por acidente).
            else:
                # Mesmo minuto com conteúdo real: preserva via sufixo de segundos.
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
    """
    Adiciona um handler de arquivo ao logging raiz, gravando o rastro da
    execução em <Resumos diários - Energia>/Logs/execucao.log.
    As pastas de Logs são criadas automaticamente.
    """
    try:
        _rotacionar_log()
        os.makedirs(config.DIR_LOGS, exist_ok=True)
        handler = logging.FileHandler(
            config.ARQUIVO_LOG, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logging.getLogger().addHandler(handler)
    except OSError as exc:
        logger.warning("Não foi possível configurar o log em arquivo: %s", exc)


_configurar_log_em_arquivo()


# -----------------------------------------------------------------------------
# CLI — JANELA (por horas ou por intervalo de DATAS)
# -----------------------------------------------------------------------------
def _parsear_data_cli(valor):
    """
    Converte "DD/MM/AAAA" em um datetime NAIVE (horário de Brasília, 00:00h).
    Retorna None se o formato for inválido.
    """
    try:
        return datetime.datetime.strptime(valor.strip(), "%d/%m/%Y")
    except (ValueError, AttributeError):
        return None


def ler_argumentos_janela():
    """
    Interpreta a CLI e devolve um dicionário descrevendo a JANELA:

      Modo "últimas horas":  python main.py --horas 48
      Modo calendário:       python main.py --de 04/09/2026 --ate 08/09/2026
                             (exato: 04/09 00:00 até 08/09 23:59)
      Flag:                  --nao-arquivar (não move relatórios antigos)

    No modo calendário a janela é [data_inicio, data_fim]; no modo horas é
    "agora - horas" sem limite superior. Retorna:
        horas            -> usada nas consultas Google News / rótulos.
        data_limite      -> limite INFERIOR exato (ou agora-horas).
        data_limite_max  -> limite SUPERIOR exato (None no modo horas).
        data_inicio/fim  -> para o cabeçalho do relatório.
        rotulo           -> texto da janela para os logs.
        arquivar         -> True/False (move relatórios antigos no fim).
    """
    parser = argparse.ArgumentParser(
        description="Motor de Busca e Clipping de Notícias do Setor Elétrico"
    )
    parser.add_argument(
        "--horas",
        type=int,
        default=None,
        help="Quantidade de horas passadas a varrear (ex.: 24, 48, 72, 96). "
        "Se nem --horas nem --de/--ate forem informados, o sistema pergunta.",
    )
    parser.add_argument(
        "--de",
        type=str,
        default=None,
        help="Modo calendário: data inicial do intervalo (DD/MM/AAAA). "
        "Use junto com --ate.",
    )
    parser.add_argument(
        "--ate",
        type=str,
        default=None,
        help="Modo calendário: data final do intervalo (DD/MM/AAAA). "
        "Use junto com --de.",
    )
    parser.add_argument(
        "--nao-arquivar",
        action="store_true",
        help="NÃO mover relatórios .docx/.csv antigos para a pasta Arquivo.",
    )
    parser.add_argument(
        "--sem-cache",
        action="store_true",
        default=False,
        help="Ignora o cache persistente de full-text (força novo scraping "
        "da mesma URL e descarta o histórico de texto baixado).",
    )
    args = parser.parse_args()

    modo_calendario = bool(args.de or args.ate)
    if modo_calendario and not (args.de and args.ate):
        parser.error("--de e --ate devem ser informados JUNTOS.")

    if modo_calendario:
        de = _parsear_data_cli(args.de)
        ate = _parsear_data_cli(args.ate)
        if de is None or ate is None:
            parser.error("Datas inválidas. Use o formato DD/MM/AAAA (ex.: 05/09/2026).")
        agora = config.agora_brasilia()
        data_inicio = datetime.datetime(de.year, de.month, de.day)
        data_fim = datetime.datetime(ate.year, ate.month, ate.day, 23, 59, 59)
        if data_inicio > data_fim:
            parser.error("A data inicial deve ser anterior ou igual à data final.")
        if data_inicio > agora:
            parser.error("A data inicial está no futuro.")
        if data_fim > agora:
            data_fim = agora  # Não há matérias "do futuro".
        horas = max(1, int((agora - data_inicio).total_seconds() // 3600) + 1)
        logger.info(
            "Modo calendário: %s a %s (janela exata [%s, %s]).",
            args.de,
            args.ate,
            data_inicio.strftime("%d/%m/%Y %H:%M"),
            data_fim.strftime("%d/%m/%Y %H:%M"),
        )
        return {
            "horas": horas,
            "data_limite": data_inicio,
            "data_limite_max": data_fim,
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "rotulo": f"{args.de} a {args.ate}",
            "arquivar": not args.nao_arquivar,
            "sem_cache": args.sem_cache,
        }

    # ---- Modo horas (original, com pergunta interativa se não informado) ----
    horas = args.horas
    if horas is None or horas <= 0:
        try:
            entrada = input("Deseja buscar as matérias de quantas horas atrás? (Padrão: 24): ")
        except (EOFError, KeyboardInterrupt):
            logger.info("Entrada cancelada. Usando padrão de %s horas.", config.DEFAULT_HOURS)
            horas = config.DEFAULT_HOURS
        else:
            entrada = (entrada or "").strip()
            if not entrada:
                logger.info("Sem entrada. Usando padrão de %s horas.", config.DEFAULT_HOURS)
                horas = config.DEFAULT_HOURS
            else:
                try:
                    horas = int(entrada)
                    if horas <= 0:
                        raise ValueError("O valor deve ser maior que zero.")
                except ValueError:
                    logger.warning(
                        "Valor inválido ('%s'). Usando padrão de %s horas.",
                        entrada,
                        config.DEFAULT_HOURS,
                    )
                    horas = config.DEFAULT_HOURS

    return {
        "horas": horas,
        "data_limite": None,
        "data_limite_max": None,
        "data_inicio": None,
        "data_fim": None,
        "rotulo": f"{horas} horas",
        "arquivar": not args.nao_arquivar,
        "sem_cache": args.sem_cache,
    }


# -----------------------------------------------------------------------------
# PRÉ-FILTRO RÁPIDO (Título + Resumo do RSS)
# -----------------------------------------------------------------------------
def pre_filtrar_rapido(noticias, filtro):
    """
    Etapa de otimização ANTES do full-text.

    PRINCÍPIO (precisão por veículo):
      - VEÍCULOS DEDICADOS AO SETOR ELÉTRICO (config.VEICULOS_ENERGIA: Canal
        Solar, CanalEnergia, MegaWhat, Cenário Energia, Brasil Energia, Eixos):
        NENHUMA matéria é descartada aqui. Tudo o que publicarem (dentro da
        janela temporal de publicação original) vai PARA O FULL-TEXT e para a
        matriz semântica — a decisão final é sempre da matriz.
      - MÍDIA GERAL (Folha, Estadão, Valor, Poder 360 etc.): além dos sinais
        fortes (clientes, chaves de Nível 2, rede de arrasto), o vocabulário
        de ENTRADA é ALARGADO (config.TERMOS_ENTRADA_MIDIA_GERAL: "luz",
        "tarifa", "apagão", "usina", "solar", "eólica", "conta de luz"...):
        qualquer um desses termos no título/resumo manda o texto para o
        scraping full-text.

    REGRA DE ENGENHARIA: este pré-filtro deve ser um SUPERCONJUNTO do filtro
    final. Ele NUNCA pode reprovar uma matéria que o full-text aprovaria (a
    citação do cliente pode estar no 4º parágrafo). A validação contextual
    rigorosa (Nível 3) fica para a avaliação completa, com o texto integral.

    Parâmetros:
        noticias (list): lista bruta de dicionários de notícias.
        filtro (SemanticFilter): instância do filtro semântico.

    Retorna: lista de notícias candidatas (a decisão final é do pipeline).
    """
    candidatas = []
    for noticia in noticias:
        veiculo = noticia.get("veiculo", "")

        # Veículos DEDICADOS ao setor elétrico: nunca pré-descartar (nem pela
        # blacklist do pré-filtro). A matriz completa decide tudo.
        if veiculo in config.VEICULOS_ENERGIA:
            candidatas.append(noticia)
            continue

        # Texto de pré-análise: título + resumo (e o full_text, se já existir).
        texto_pre = f"{noticia['titulo']} {noticia['resumo']}"

        # Verifica se a blacklist já fura o título/resumo — aí descarta
        # (apenas para mídia geral; nos veículos de energia a matriz decide).
        normalizado_pre = filtro._normalizar(texto_pre)
        if filtro._nivel4_blacklist(normalizado_pre):
            logger.debug(
                "Pré-filtro descartou (blacklist): %s", noticia["titulo"][:60]
            )
            continue

        # Sinalização forte já no título/resumo: cliente citado, chave de
        # Nível 2 ou palavra ampla do setor. Qualquer uma basta para manter.
        tem_cliente = bool(filtro._nivel1_clientes(normalizado_pre))
        tem_nivel2 = filtro._nivel2_macro_regulatorio(normalizado_pre)
        tem_palavra_ampla = any(
            filtro._contem(normalizado_pre, filtro._normalizar(palavra))
            for palavra in config.PALAVRAS_ARRASTO
        )
        # O termo também é NORMALIZADO (remove acentos) antes do match, pois
        # normalizado_pre já vem sem acentos — senão metade dos termos bônus
        # (ex.: 'transmissão') nunca dispararia.
        tem_termo_setor = any(
            filtro._contem(normalizado_pre, filtro._normalizar(termo))
            for termo in config.PRE_FILTRO_TERMOS_BONUS
        )
        # Vocabulário ALARGADO de entrada para a mídia geral.
        tem_termo_entrada = any(
            filtro._contem(normalizado_pre, filtro._normalizar(palavra))
            for palavra in config.TERMOS_ENTRADA_MIDIA_GERAL
        )

        if (
            tem_cliente
            or tem_nivel2
            or tem_palavra_ampla
            or tem_termo_setor
            or tem_termo_entrada
        ):
            candidatas.append(noticia)

    logger.info(
        "Pré-filtro: %d notícia(s) mantida(s) de %d (descarte rápido de irrelevantes).",
        len(candidatas),
        len(noticias),
    )
    return candidatas


# -----------------------------------------------------------------------------
# AVALIAÇÃO INDIVIDUAL DE UMA CANDIDATA (full-text + matriz semântica)
# -----------------------------------------------------------------------------
def avaliar_candidata(motor_engine, filtro, noticia):
    """
    Processa UMA notícia candidata: busca full-text + data de publicação
    original no HTML, aplica a janela temporal estrita e a matriz semântica.

    Criada como função isolada para ser executada em paralelo
    (ThreadPoolExecutor), reduzindo drasticamente o tempo da análise
    full-text (o maior gargalo de rede do pipeline).

    Retorna a tupla (status, noticia_atualizada):
        - "aprovada"  → passou na matriz (Níveis 1 a 4).
        - "data_fora" → data de publicação ORIGINAL (HTML) fora da janela.
        - "sem_data"  → sem data original em RSS nem HTML (descarta).
    """
    # Obtém o full-text, a DATA DE PUBLICAÇÃO ORIGINAL (via meta tags do
    # HTML) e a URL final resolvida.
    texto_completo, data_pub_html, url_final = motor_engine._obter_texto_e_data(
        noticia["link"]
    )

    # REGRA CRÍTICA DE ENGENHARIA (filtro temporal):
    # A data extraída do HTML é a fonte MAIS confiável da publicação original
    # (article:published_time / datePublished). Se ela existir e estiver FORA
    # do intervalo [data_limite, data_limite_max], descarta imediatamente —
    # mesmo que o feed a tenha listado (o feed pode refletir apenas atualização).
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

    # Entrada sem data de publicação original (RSS) e sem data recuperável do
    # HTML → não pode ser validada na janela de tempo. Descarta (a regra nunca
    # usa 'updated' para aceitar matéria).
    if data_pub_html is None and noticia.get("data_publicacao") is None:
        return ("sem_data", noticia)

    # Atualiza a data com a fonte mais confiável (HTML), se disponível.
    if data_pub_html is not None:
        noticia["data_publicacao"] = data_pub_html

    # Usa a URL final (real) para o relatório e encurtamento.
    noticia["link"] = url_final

    if not texto_completo.strip():
        # Sem full-text (ex.: links do Google News), usa título+resumo como
        # fallback — melhor que descartar às cegas.
        texto_avaliado = f"{noticia['titulo']} {noticia['resumo']}"
    else:
        texto_avaliado = texto_completo

    noticia["full_text"] = texto_completo
    noticia["texto_avaliado"] = texto_avaliado

    # Avalia com o SemanticFilter (Níveis 1 a 4).
    is_relevante, clientes_citados = filtro.avaliar(texto_avaliado)
    noticia["is_relevante"] = is_relevante
    noticia["clientes_citados"] = clientes_citados

    if is_relevante:
        return ("aprovada", noticia)
    return ("reprovada", noticia)


# -----------------------------------------------------------------------------
# PIPELINE PRINCIPAL
# -----------------------------------------------------------------------------
def executar_pipeline(janela):
    """
    Executa toda a cadeia do motor e retorna o caminho do arquivo gerado.

    janela (dict, de ler_argumentos_janela): define horas/janelas e flags.

    Etapas:
        1. Coleta via ScraperEngine (RSS + busca interna + Google News).
        2. Pré-filtro rápido (título + resumo).
        3. Avaliação semântica completa do full-text (Níveis 1 a 4),
           executada em paralelo para performance.
        4. Encurtamento + validação dos links (IS.GD → TinyURL → original).
        5. Exportação do .docx, manifesto .csv e arquivamento de antigos.
    """
    inicio = time.time()
    horas_passadas = janela["horas"]

    # ---- 1. COLETA ----
    logger.info("=" * 70)
    logger.info("INICIANDO COLETA DE NOTÍCIAS — janela: %s", janela["rotulo"])
    logger.info("=" * 70)
    motor = ScraperEngine(
        horas_passadas=horas_passadas,
        data_limite_max=janela.get("data_limite_max"),
        data_limite=janela.get("data_limite"),
        sem_cache=janela.get("sem_cache", False),
    )
    todas_as_noticias = motor.coletar_todos()

    # ------ SAÚDE DOS FEEDS: registra o run e dispara alertas -------
    historico_saude = saude.carregar_historico()
    historico_saude = saude.registrar_run(historico_saude, motor, janela["rotulo"])
    for alerta_saude in saude.verificar_alertas(historico_saude):
        logger.warning(alerta_saude)
    saude.salvar_historico(historico_saude)

    if not todas_as_noticias:
        logger.warning("Nenhuma notícia coletada. Nada a gerar.")
        return None

    # ---- 2. PRÉ-FILTRO RÁPIDO ----
    filtro = SemanticFilter()
    candidatas = pre_filtrar_rapido(todas_as_noticias, filtro)

    if not candidatas:
        logger.warning("Nenhuma notícia aprovou o pré-filtro. Nada a gerar.")
        return None

    # ---- 3. AVALIAÇÃO SEMÂNTICA COMPLETA (full-text) em paralelo ----
    logger.info("Analisando full-text e aplicando matriz semântica (Níveis 1 a 4)...")
    aprovadas = []
    descartadas_por_data_html = 0
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
                descartadas_por_data_html += 1
            elif status == "sem_data":
                sem_data += 1
            else:
                reprovadas += 1

    if descartadas_por_data_html:
        logger.info(
            "%d notícia(s) descartada(s) porque a data de publicação original "
            "(HTML) caiu fora da janela (%s).",
            descartadas_por_data_html,
            janela["rotulo"],
        )

    # Persistência do cache de full-text (URLs novas baixadas na análise).
    motor._salvar_cache()

    # Ordenação final:
    #   REGRA DE NEGÓCIO: matérias com CLIPPING (citam cliente(s)) vão SEMPRE
    #   ao TOPO do resumo, independentemente de qual cliente é. Dentro de cada
    #   grupo (com/sem clipping), a ordem é cronológica (mais recente primeiro).
    aprovadas.sort(
        key=lambda n: (
            1 if (n.get("clientes_citados") or []) else 0,
            n.get("data_publicacao") or _data_fallback(),
        ),
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
        # Última chance de resolver um link ainda preso no Google News: a
        # decodificação pode falhar por rate-limit durante a análise em
        # paralelo; aqui, com volume mínimo (só as aprovadas), a chance de
        # sucesso é alta. Falhou → mantém o link original (sem regressão).
        if motor._eh_link_google_news(link):
            canonica = motor._resolver_url_google_news(link)
            if canonica:
                logger.info(
                    "Link GN resolvido no retry: %s -> %s", link[:60], canonica[:80]
                )
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
    )
    _salvar_manifesto_csv(caminho_arquivo, aprovadas)
    if janela.get("arquivar"):
        _arquivar_relatorios_antigos(caminho_arquivo)

    duracao = time.time() - inicio
    logger.info("=" * 70)
    logger.info("MÉTRICAS DA EXECUÇÃO (janela: %s):", janela["rotulo"])
    logger.info(
        "  • %d matéria(s) coletada(s) (bruto).",
        len(todas_as_noticias),
    )
    logger.info(
        "  • %d matéria(s) passaram no filtro temporal (data original na janela).",
        len(aprovadas) + reprovadas,
    )
    logger.info(
        "  • %d matéria(s) avaliada(s) no full-text (matriz N1–N4) — %d com texto completo raspado.",
        len(aprovadas) + reprovadas,
        com_fulltext,
    )
    logger.info("  • %d matéria(s) APROVADA(s) e salvas no .docx.", len(aprovadas))
    logger.info("=" * 70)
    logger.info("RESUMO FINAL: %d notícia(s) no relatório.", len(aprovadas))
    logger.info("Arquivo salvo em: %s", caminho_arquivo)
    logger.info("Tempo total: %.1f segundos.", duracao)
    logger.info("=" * 70)
    return caminho_arquivo


# -----------------------------------------------------------------------------
# MANIFESTO CSV (rastreabilidade de cada entrega)
# -----------------------------------------------------------------------------
def _salvar_manifesto_csv(caminho_docx, aprovadas):
    """
    Grava, ao lado do .docx, um manifesto <mesmo_nome>.csv com as entregas:
    veículo; título; clientes citados; data de publicação original; link curto;
    link original; origem. Usa separador ';' e codificação utf-8-sig (abre
    direto no Excel preservando acentos).
    """
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
# ARQUIVAMENTO DOS RELATÓRIOS ANTERIORES (mantém a pasta de entrega limpa)
# -----------------------------------------------------------------------------
def _arquivar_relatorios_antigos(caminho_atual):
    """
    Move para a subpasta Relatorios/Arquivo os .docx/.csv ANTIGOS (não o recém-gerado).
    Assim a pasta de entrega fica só com a entrega mais recente e o histórico
    preservado numa subpasta (fonte de consulta/auditoria).
    """
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
            # Nunca arquiva a entrega recém-gerada (docx nem o manifesto csv).
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


# -----------------------------------------------------------------------------
# FALLBACK DE DATA (para a ordenação)
# -----------------------------------------------------------------------------
def _data_fallback():
    """
    Data usada para ordenar notícias sem data de publicação (trata como as
    mais antigas — vão para o fim do relatório.
    """
    return datetime.datetime(1970, 1, 1)


# -----------------------------------------------------------------------------
# BLOCO PRINCIPAL
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    janela = ler_argumentos_janela()
    caminho = executar_pipeline(janela)
    if caminho:
        logger.info("Concluído! Abra o arquivo: %s", caminho)
    else:
        logger.info("Nenhum relatório foi gerado nesta execução.")