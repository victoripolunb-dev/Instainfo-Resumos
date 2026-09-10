# =============================================================================
# config.py
# ---------
# Configuração CENTRAL do módulo genérico "Monitoramento Inteligente".
#
# Ao contrário dos módulos dedicados (Energia/ABRASCA), este módulo NÃO
# trava clientes, palavras-chave, veículos ou períodos no código. Tudo isso
# vem da DEMANDA (demanda.json, gerado a partir do modelo de demanda) — e a
# demanda é injetada em runtime por demanda.py (que ajusta os atributos deste
# módulo antes da execução do pipeline).
#
# Este arquivo concentra apenas o que é GENÉRICO e estável:
#   - Catálogo de veículos (unificado Energia + ABRASCA + G1 + JOTA…), com
#     feeds RSS e domínio para fallback no Google News.
#   - Portais com busca interna ("Lupa").
#   - Controles globais: timeouts, workers, rate-limit do Google News,
#     rodízio de User-Agent, cache de full-text.
#   - Caminhos base de entrega (Desktop\Instainfo Resumos - Entregas\Monitoramento
#     Inteligente\Entregas\<Cliente>).
# =============================================================================

import datetime
import os


# -----------------------------------------------------------------------------
# FUSO HORÁRIO DE REFERÊNCIA (HORÁRIO DE BRASÍLIA)
# -----------------------------------------------------------------------------
try:
    from zoneinfo import ZoneInfo

    FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")
except Exception:
    FUSO_BRASILIA = datetime.timezone(datetime.timedelta(hours=-3))


def agora_brasilia():
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .astimezone(FUSO_BRASILIA)
        .replace(tzinfo=None)
    )


def para_brasilia(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(FUSO_BRASILIA).replace(tzinfo=None)


# -----------------------------------------------------------------------------
# CAMINHOS DE ENTREGA
# -----------------------------------------------------------------------------
# Raiz genérica: Desktop\Instainfo Resumos - Entregas\Monitoramento
# Inteligente\Entregas\<Cliente>.
# Os caminhos por cliente (DIR_RELATORIOS, DIR_ARQUIVO, DIR_LOGS, Cache…) são
# PREENCHIDOS por demanda.py no carregamento (config.demanda_paths(cliente)).
USER_PROFILE = os.environ.get("USERPROFILE", os.path.expanduser("~"))
MODULO_NOME = "Monitoramento Inteligente"
RESUMOS_RAIZ = os.path.join(
    USER_PROFILE, "Desktop", "Instainfo Resumos - Entregas", MODULO_NOME, "Entregas"
)

# Valores padrão (placeholder "Cliente"): garantem que imports não quebrem
# antes de uma demanda ser carregada. demanda.py sobrescreve estes atributos.
BASE_DIR = os.path.join(RESUMOS_RAIZ, "Cliente")
DIR_RELATORIOS = os.path.join(BASE_DIR, "Relatórios")
DIR_ARQUIVO = os.path.join(DIR_RELATORIOS, "Arquivo")
DIR_LOGS = os.path.join(BASE_DIR, "Logs")
ARQUIVO_LOG = os.path.join(DIR_LOGS, "execucao.log")
ARQUIVO_SAUDE_FEEDS = os.path.join(DIR_LOGS, "saude_feeds.json")
DIR_CACHE = os.path.join(BASE_DIR, "Cache")
ARQUIVO_CACHE_FULLTEXT = os.path.join(DIR_CACHE, "fulltext.json")

MAX_LOGS_ARQUIVADOS = 10
CACHE_MAX_ENTRADAS = 4000
CACHE_FLUSH_A_CADA = 50

FEED_ALERTA_RUNS_SEM_MATERIA = 3
SAUDE_RUNS_MAXIMO = 30

TIMEOUT = 10

# -----------------------------------------------------------------------------
# FALLBACK SCRAPLING (PLANO B) — bypass de anti-bot/403/layout
# -----------------------------------------------------------------------------
# Quando uma requisição do requests falha (exceção de rede, HTTP 403/429/5xx,
# página-desafio de Cloudflare) ou o seletor de <p> volta vazio, o scraper.py
# tenta baixar o mesmo HTML através do Scrapling (impersonação de TLS/headers
# de navegador real). Import é preguiçoso: sem `pip install "scrapling[fetchers]"`
# o plano B vira no-op (retorna None) e o pipeline segue igual a antes.
SCRAPLING_FALLBACK = True           # liga/desliga o plano B sem mexer no código.
SCRAPLING_STEALTH = False           # True = StealthyFetcher (Chromium headless)
                                    # em último caso — mais lento e pesado.
SCRAPLING_FALLBACK_ALVO_STATUS = (403, 429, 500, 502, 503)

DEFAULT_HOURS = 24


# -----------------------------------------------------------------------------
# RODÍZIO DE USER-AGENTS
# -----------------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


# -----------------------------------------------------------------------------
# CATÁLOGO DE VEÍCULOS (unificado Energia + ABRASCA + G1 + JOTA…)
# -----------------------------------------------------------------------------
# Cada veículo tem:
#   - 'rss': lista de feeds diretos (PRIORITÁRIOS). Vazia = só fallback GN.
#   - 'dominio': usado no fallback Google News (site:<dominio> when:Nh).
# A demanda escolhe por NOME os veículos deste catálogo.
# -----------------------------------------------------------------------------
CATALOGO_VEICULOS = {
    "Valor Econômico": {
        "rss": ["https://www.valor.com.br/ultimas-noticias/feed"],
        "dominio": "valor.globo.com",
    },
    "Estadão": {
        "rss": ["https://www.estadao.com.br/feed/"],
        "dominio": "estadao.com.br",
    },
    "Estadão | Broadcast": {
        "rss": ["https://www.estadao.com.br/economia/feed/"],
        "dominio": "broadcast.com.br",
    },
    "Estadão | E-Investidor": {
        "rss": ["https://einvestidor.estadao.com.br/feed/"],
        "dominio": "einvestidor.estadao.com.br",
    },
    "Folha de S. Paulo": {
        "rss": [
            "https://feeds.folha.uol.com.br/mercado/rss091.xml",
            "https://feeds.folha.uol.com.br/poder/rss091.xml",
        ],
        "dominio": "folha.uol.com.br",
    },
    "O Globo": {
        "rss": ["https://oglobo.globo.com/rss/ultimas-noticias/"],
        "dominio": "oglobo.globo.com",
    },
    "G1": {
        "rss": [
            "https://g1.globo.com/rss/g1/",
            "https://g1.globo.com/rss/g1/economia/",
        ],
        "dominio": "g1.globo.com",
    },
    "Poder 360": {
        "rss": ["https://www.poder360.com.br/feed/"],
        "dominio": "poder360.com.br",
    },
    "CNN Brasil": {
        "rss": ["https://www.cnnbrasil.com.br/feed/"],
        "dominio": "cnnbrasil.com.br",
    },
    "Metrópoles": {
        "rss": ["https://www.metropoles.com/feed"],
        "dominio": "metropoles.com",
    },
    "Veja": {
        "rss": [],
        "dominio": "veja.abril.com.br",
    },
    "Portal UOL": {
        "rss": ["https://rss.uol.com.br/feed/noticias.xml"],
        "dominio": "uol.com.br",
    },
    "Portal JOTA": {
        "rss": ["https://www.jota.info/feed"],
        "dominio": "jota.info",
    },
    "Brazil Journal": {
        "rss": ["https://braziljournal.com/feed"],
        "dominio": "braziljournal.com",
    },
    "InfoMoney": {
        "rss": ["https://www.infomoney.com.br/feed/"],
        "dominio": "infomoney.com.br",
    },
    "Portal Exame": {
        "rss": ["https://exame.com/feed/"],
        "dominio": "exame.com",
    },
    "Correio Braziliense": {
        "rss": [],
        "dominio": "correiobraziliense.com.br",
    },
    "BR Investing": {
        "rss": [],
        "dominio": "br.investing.com",
    },
    "NeoFeed": {
        "rss": ["https://neofeed.com.br/feed/"],
        "dominio": "neofeed.com.br",
    },
    "Agência Brasil": {
        "rss": ["https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml"],
        "dominio": "agenciabrasil.ebc.com.br",
    },
    # ---- Setor elétrico (do módulo Energia) ----
    "CanalEnergia": {
        "rss": ["https://www.canalenergia.com.br/rss"],
        "dominio": "canalenergia.com.br",
    },
    "MegaWhat": {
        "rss": ["https://megawhat.energy/feed/"],
        "dominio": "megawhat.energy",
    },
    "Agência Eixos": {
        "rss": ["https://www.eixos.com.br/feed/"],
        "dominio": "eixos.com.br",
    },
    "Brasil Energia": {
        "rss": ["https://brasilenergia.com.br/feed"],
        "dominio": "brasilenergia.com.br",
    },
    "Agência iNFRA": {
        "rss": ["https://agenciainfra.com/blog/feed/"],
        "dominio": "agenciainfra.com",
    },
    "Cenário Energia": {
        "rss": ["https://cenarioenergia.com.br/feed/"],
        "dominio": "cenarioenergia.com.br",
    },
    "Canal Solar": {
        "rss": ["https://canalsolar.com.br/feed/"],
        "dominio": "canalsolar.com.br",
    },
}

# Veículos que a demanda conhece por apelidos informais → nomes oficiais.
ALIASES_VEICULOS = {
    "valor": "Valor Econômico",
    "valor econômico": "Valor Econômico",
    "valor economico": "Valor Econômico",
    "estadao": "Estadão",
    "estadão": "Estadão",
    "estado de s. paulo": "Estadão",
    "folha": "Folha de S. Paulo",
    "folha de s.paulo": "Folha de S. Paulo",
    "folha de sao paulo": "Folha de S. Paulo",
    "folha de s. paulo": "Folha de S. Paulo",
    "globo": "O Globo",
    "o globo": "O Globo",
    "g1": "G1",
    "poder360": "Poder 360",
    "poder 360": "Poder 360",
    "cnn brasil": "CNN Brasil",
    "cnn": "CNN Brasil",
    "metropoles": "Metrópoles",
    "metrópoles": "Metrópoles",
    "veja": "Veja",
    "uol": "Portal UOL",
    "portal uol": "Portal UOL",
    "jota": "Portal JOTA",
    "portal jota": "Portal JOTA",
    "brazil journal": "Brazil Journal",
    "braziljournal": "Brazil Journal",
    "infomoney": "InfoMoney",
    "exame": "Portal Exame",
    "portal exame": "Portal Exame",
    "correio braziliense": "Correio Braziliense",
    "br investing": "BR Investing",
    "neofeed": "NeoFeed",
    "agência brasil": "Agência Brasil",
    "agencia brasil": "Agência Brasil",
    "canalenergia": "CanalEnergia",
    "megawhat": "MegaWhat",
    "agência eixos": "Agência Eixos",
    "agencia eixos": "Agência Eixos",
    "brasil energia": "Brasil Energia",
    "agência infra": "Agência iNFRA",
    "agencia infra": "Agência iNFRA",
    "cenário energia": "Cenário Energia",
    "cenario energia": "Cenário Energia",
    "canal solar": "Canal Solar",
    "broadcast": "Estadão | Broadcast",
    "estadão | broadcast": "Estadão | Broadcast",
    "estadao | broadcast": "Estadão | Broadcast",
    "e-investidor": "Estadão | E-Investidor",
    "e investidor": "Estadão | E-Investidor",
}


GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419"


# -----------------------------------------------------------------------------
# BUSCA INTERNA DOS VEÍCULOS ("LUPA") — TARGETED SEARCH
# -----------------------------------------------------------------------------
# Portais com busca server-side (WordPress). A demanda também injeta os termos
# a buscar (config.BUSCA_TERMOS).
# -----------------------------------------------------------------------------
BUSCA_SITES = {
    "Canal Solar": {
        "url": "https://canalsolar.com.br/?s={termo}&feed=rss",
        "tipo": "wp",
    },
    "NeoFeed": {
        "url": "https://neofeed.com.br/?s={termo}&feed=rss",
        "tipo": "wp",
    },
    "Brazil Journal": {
        "url": "https://braziljournal.com/?s={termo}&feed=rss",
        "tipo": "wp",
    },
    "Brasil Energia": {
        "url": "https://brasilenergia.com.br/?s={termo}&feed=rss",
        "tipo": "wp",
    },
    "Cenário Energia": {
        "url": "https://cenarioenergia.com.br/?s={termo}&feed=rss",
        "tipo": "wp",
    },
}

BUSCA_MAX_POR_TERMO = 8

# -----------------------------------------------------------------------------
# WORKERS
# -----------------------------------------------------------------------------
ANALISE_WORKERS = 6
COLETA_WORKERS = 6

# -----------------------------------------------------------------------------
# GOOGLE NEWS — CONTROLES DE RATE-LIMIT
# -----------------------------------------------------------------------------
GN_MAX_FALHAS_SEGUIDAS = 4
GN_JITTER_MIN = 0.8
GN_JITTER_MAX = 1.8
GN_JITTER_FATOR = 2.0
GN_JITTER_TETO = 8.0
GN_JITTER_RECUPERACAO = 0.7

GN_SKIP_TERMO_ATE_ITENS = 6


# -----------------------------------------------------------------------------
# MATRIZES SEMÂNTICAS PADRÃO (sobrescritas pela demanda quando informadas)
# -----------------------------------------------------------------------------
# O SemanticFilter lê os seguintes atributos em runtime. A demanda preenche:
#   CLIENTES                {nome: [variações, representantes]}
#   BUSCA_TERMOS            [palavras-chave a buscar na Lupa/GN]
#   PALAVRAS_CHAVE          [keywords de relevância (N2)]
#   TERMOS_CONTEXTO         [termos que CONFIRMAM o tema (coocorrência)]
#   TERMOS_EXCLUSAO         [sinais de falso tema (override — N4)]
#   DESTACAR_CLIPPING       bool — citou cliente → destaque com selo
# Os padrões abaixo apenas garantem comportamento seguro se algo vier vazio.
CLIENTES = {}
BUSCA_TERMOS = []
PALAVRAS_CHAVE = []
TERMOS_CONTEXTO = []
TERMOS_EXCLUSAO = []
DESTACAR_CLIPPING = True

# Veículos selecionados pela demanda (preenchido por demanda.py).
VEICULOS = {}

# "Chaves fortes": keywords que, sozinhas no texto, já indicam o tema
# (sem exigir coocorrência). A demanda pode marcar quais keywords são fortes.
CHAVES_CHAVE_FORTES = []

# Blacklist GLOBAL de ruído (não é tema): ruídos transversais enviados em
# qualquer demanda (esporte, crime, clima, entretenimento…). É somada aos
# TERMOS_EXCLUSAO da demanda.
BLACKLIST_GLOBAL = [
    "futebol",
    "campeonato",
    "torneio",
    "jogador",
    "atleta",
    "olimpíadas",
    "olimpiadas",
    "gol de",
    "partida de futebol",
    "previsão do tempo",
    "previsao do tempo",
    "temperatura máxima",
    "temperatura maxima",
    "fenômeno climático",
    "fenomeno climatico",
    "chuva forte",
    "tempestade tropical",
    "furacão",
    "furacao",
    "assassinato",
    "homicídio",
    "homicidio",
    "latrocínio",
    "latrocinio",
    "tiroteio",
    "tráfico de drogas",
    "trafico de drogas",
    "tráfico de armas",
    "trafico de armas",
    "contrabando",
    "desmanche",
    "big brother",
    "reality show",
]

# Blacklist EFETIVA = global + termos de exclusão da demanda.
# (demanda.py sobrescreve este atributo no carregamento; o default garante
# tensegurança caso o SemanticFilter seja usado em testes sem demanda.)
BLACKLIST = BLACKLIST_GLOBAL

TITULO_DOCUMENTO = "📈 Monitoramento Inteligente"
DATA_FORMATO = "%d de %B de %Y"
ARQUIVO_FORMATO = "Clipping_{cliente}_{agora:%Y-%m-%d_%Hh%M}.docx"


# -----------------------------------------------------------------------------
# ENCURTADORES DE LINK (IS.GD → TinyURL → URL original)
# -----------------------------------------------------------------------------
ISGD_API_URL = "https://is.gd/create.php"
ISGD_TIMEOUT = 5

TINYURL_API_URL = "https://tinyurl.com/api-create.php"
TINYURL_TIMEOUT = 5

VALIDATION_TIMEOUT = 5
STATUS_VALIDO_MAX = 400


# -----------------------------------------------------------------------------
# PATHS POR CLIENTE (chamado por demanda.py no carregamento)
# -----------------------------------------------------------------------------
def configurar_caminhos(cliente_slug):
    """
    (Re)aponta os caminhos de entrega/arquivamento/log/cache para o cliente
    da demanda atual. Deve ser chamado ANTES de qualquer execução do pipeline.
    """
    global BASE_DIR, DIR_RELATORIOS, DIR_ARQUIVO, DIR_LOGS, ARQUIVO_LOG
    global ARQUIVO_SAUDE_FEEDS, DIR_CACHE, ARQUIVO_CACHE_FULLTEXT
    BASE_DIR = os.path.join(RESUMOS_RAIZ, cliente_slug)
    DIR_RELATORIOS = os.path.join(BASE_DIR, "Relatórios")
    DIR_ARQUIVO = os.path.join(DIR_RELATORIOS, "Arquivo")
    DIR_LOGS = os.path.join(BASE_DIR, "Logs")
    ARQUIVO_LOG = os.path.join(DIR_LOGS, "execucao.log")
    ARQUIVO_SAUDE_FEEDS = os.path.join(DIR_LOGS, "saude_feeds.json")
    DIR_CACHE = os.path.join(BASE_DIR, "Cache")
    ARQUIVO_CACHE_FULLTEXT = os.path.join(DIR_CACHE, "fulltext.json")