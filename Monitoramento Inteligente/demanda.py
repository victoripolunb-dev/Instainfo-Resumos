# =============================================================================
# demanda.py
# ----------
# Carregador de DEMANDA para o módulo genérico "Monitoramento Inteligente".
#
# A demanda (demanda.json, preenchido a partir do modelo-demanda.md) define
# TUDO o que varia por cliente/ocasião:
#   - cliente e variações/representantes
#   - período exato (data_inicio / data_fim)
#   - veículos a monitorar (por nome, aceitando apelidos)
#   - palavras-chave (+ quais são "fortes", que aprovam sozinhas)
#   - termos de contexto positivo (confirmam o tema — coocorrência)
#   - termos de exclusão (sinalizam falso tema — override)
#   - se o cliente citado deve ser destacado como clipping
#
# Ao carregar, a demanda é INJETADA no módulo config (config.CLIENTES,
# config.VEICULOS, config.BUSCA_TERMOS, config.PALAVRAS_CHAVE etc.) e os
# caminhos de entrega são apontados para a pasta do cliente.
# =============================================================================

import datetime
import json
import logging
import os
import re
import unicodedata

import config

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# UTILITÁRIOS
# -----------------------------------------------------------------------------
def _slug_cliente(nome):
    """Nome do cliente em formato seguro para nome de pasta (sem acentos e
    sem caracteres inválidos do Windows)."""
    nome = nome.strip()
    nome_sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", nome)
        if unicodedata.category(c) != "Mn"
    )
    slug = re.sub(r'[\\/:*?"<>|]+', "-", nome_sem_acento).strip().rstrip(".")
    return slug or "Cliente"


def _limpar_lista(valor):
    """Normaliza uma lista que pode vir como array OU como string separada por
    vírgula, ponto e vírgula ou enter."""
    if valor is None:
        return []
    if isinstance(valor, str):
        itens = re.split(r"[,;]|\n", valor)
    else:
        itens = valor
    resultado = []
    for item in itens:
        texto = str(item).strip()
        if texto and texto not in resultado:
            resultado.append(texto)
    return resultado


def _parsear_data(valor):
    """'DD/MM/AAAA' (ou ISO) -> datetime na zero hora de Brasília."""
    valor = str(valor or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(valor, fmt)
        except ValueError:
            continue
    raise ValueError(f"Data inválida: {valor!r} (use DD/MM/AAAA ou AAAA-MM-DD)")


def _resolver_veiculo(nome):
    """Resolve nome/apelido de veículo para o nome oficial do catálogo."""
    nome_limpo = nome.strip()
    if nome_limpo in config.CATALOGO_VEICULOS:
        return nome_limpo
    return config.ALIASES_VEICULOS.get(nome_limpo.lower())


# -----------------------------------------------------------------------------
# CARREGADOR PRINCIPAL
# -----------------------------------------------------------------------------
def carregar(caminho_demanda, cliente_override=None):
    """
    Lê demanda.json e injeta tudo no config.

    Parâmetros:
        caminho_demanda (str): caminho absoluto do arquivo JSON da demanda.
        cliente_override (str | None): cliente informado na linha de comando
            substitui o do JSON (útil para reuso da mesma base).

    Retorna dict com os dados normalizados (cliente, slug, período,
    veículos selecionados, flag de destaque etc.) — usado pelo main.py.
    """
    with open(caminho_demanda, "r", encoding="utf-8") as arquivo:
        dados = json.load(arquivo)

    cliente = (cliente_override or dados.get("cliente") or "").strip()
    if not cliente:
        raise ValueError("A demanda não informou o 'cliente'.")

    slug = _slug_cliente(cliente)
    config.configurar_caminhos(slug)

    # ---- Cliente + variações + representantes (Nível 1) ----
    variacoes = _limpar_lista(dados.get("variacoes"))
    representantes = _limpar_lista(dados.get("representantes"))
    variantes = []
    for v in [cliente] + variacoes + representantes:
        if v not in variantes:
            variantes.append(v)
    config.CLIENTES = {cliente: variantes}

    # ---- Palavras-chave / contexto / exclusão ----
    config.PALAVRAS_CHAVE = _limpar_lista(dados.get("palavras_chave"))
    config.CHAVES_CHAVE_FORTES = _limpar_lista(
        dados.get("palavras_chave_fortes")
    )
    config.TERMOS_CONTEXTO = _limpar_lista(dados.get("termos_contexto"))
    config.TERMOS_EXCLUSAO = _limpar_lista(dados.get("termos_exclusao"))
    config.DESTACAR_CLIPPING = bool(
        dados.get("destacar_clipping", True)
    )
    config.BLACKLIST = config.BLACKLIST_GLOBAL + config.TERMOS_EXCLUSAO

    # ---- Termos de busca (Lupa + Google News por termo) ----
    # Cliente/representantes primeiro (alvos diretos), depois as keywords.
    termos_busca = []
    for termo in [cliente] + representantes + config.PALAVRAS_CHAVE:
        if termo not in termos_busca:
            termos_busca.append(termo)
    config.BUSCA_TERMOS = termos_busca

    # ---- Veículos (resolução por nome/apelido) ----
    selecionados = {}
    nao_encontrados = []
    for nome in _limpar_lista(dados.get("veiculos")):
        oficial = _resolver_veiculo(nome)
        if oficial and oficial in config.CATALOGO_VEICULOS:
            selecionados[oficial] = config.CATALOGO_VEICULOS[oficial]
        else:
            nao_encontrados.append(nome)
    if not selecionados:
        raise ValueError(
            "Nenhum veículo reconhecido na demanda. Confira os nomes em "
            "'veiculos' (o catálogo é config.CATALOGO_VEICULOS)."
        )
    if nao_encontrados:
        logger.warning(
            "Veículos não reconhecidos e IGNORADOS: %s",
            ", ".join(nao_encontrados),
        )
    config.VEICULOS = selecionados

    # ---- Documento ----
    config.TITULO_DOCUMENTO = f"📈 Monitoramento Inteligente - {cliente}"

    return {
        "cliente": cliente,
        "cliente_slug": slug,
        "contexto": str(dados.get("contexto") or ""),
        "data_inicio": _parsear_data(dados.get("data_inicio")),
        "data_fim": _parsear_data(dados.get("data_fim")),
        "veiculos": list(selecionados),
        "nao_encontrados": nao_encontrados,
        "destacar_clipping": config.DESTACAR_CLIPPING,
        "titulo_documento": config.TITULO_DOCUMENTO,
    }


def caminho_demanda_padrao():
    """Procura o demanda.json na subpasta demandas/ (última demanda usada);
    mantém fallback na raiz do módulo para compatibilidade."""
    raiz_modulo = os.path.dirname(os.path.abspath(__file__))
    na_subpasta = os.path.join(raiz_modulo, "demandas", "demanda.json")
    if os.path.isfile(na_subpasta):
        return na_subpasta
    return os.path.join(raiz_modulo, "demanda.json")