# =============================================================================
# config.py
# ---------
# Arquivo de configuração central do "Motor de Busca e Clipping de Notícias
# de Mercado de Capitais" (projeto ABRASCA).
#
# Este módulo concentra TODAS as constantes e estruturas de dados usadas pelo
# sistema: caminho de saída, lista dos veículos com seus feeds RSS, as
# entidades-alvo (clientes), as matrizes de filtragem semântica (Níveis 1 a 4)
# e a blacklist de ambiguidade.
#
# Mantendo tudo aqui, qualquer alteração de negócio (novo veículo, novo
# cliente, nova keyword) é feita em UM único ponto, sem tocar na lógica.
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


PROJETO_DIR = "ABRASCA"
PROJETO_PASTA_ENTREGA = "Resumos diários - ABRASCA"

# -----------------------------------------------------------------------------
# CAMINHOS DE SAÍDA
# -----------------------------------------------------------------------------
USER_PROFILE = os.environ.get("USERPROFILE", os.path.expanduser("~"))
BASE_DIR = os.path.join(USER_PROFILE, "Desktop", "Instainfo Resumos - Entregas", PROJETO_DIR)

# -----------------------------------------------------------------------------
# ORGANIZAÇÃO DAS ENTREGAS EM PASTAS
# -----------------------------------------------------------------------------
DIR_RESUMOS = os.path.join(BASE_DIR, PROJETO_PASTA_ENTREGA)
DIR_RELATORIOS = os.path.join(DIR_RESUMOS, "Relatórios")
DIR_ARQUIVO = os.path.join(DIR_RELATORIOS, "Arquivo")
DIR_LOGS = os.path.join(DIR_RESUMOS, "Logs")
ARQUIVO_LOG = os.path.join(DIR_LOGS, "execucao.log")

MAX_LOGS_ARQUIVADOS = 10

# -----------------------------------------------------------------------------
# SAÚDE DOS FEEDS
# -----------------------------------------------------------------------------
ARQUIVO_SAUDE_FEEDS = os.path.join(DIR_LOGS, "saude_feeds.json")
FEED_ALERTA_RUNS_SEM_MATERIA = 3
SAUDE_RUNS_MAXIMO = 30

# -----------------------------------------------------------------------------
# CACHE DE FULL-TEXT
# -----------------------------------------------------------------------------
DIR_CACHE = os.path.join(DIR_RESUMOS, "Cache")
ARQUIVO_CACHE_FULLTEXT = os.path.join(DIR_CACHE, "fulltext.json")

CACHE_MAX_ENTRADAS = 4000
CACHE_FLUSH_A_CADA = 50


# -----------------------------------------------------------------------------
# TIMEOUT PADRÃO (segundos)
# -----------------------------------------------------------------------------
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


# -----------------------------------------------------------------------------
# CRONOGRAMA / JANELA DE TEMPO
# -----------------------------------------------------------------------------
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
# VEÍCULOS (FONTES) — 18 portais de Mercado de Capitais
# -----------------------------------------------------------------------------
# Estratégia de coleta híbrida por veículo:
#   - 'rss': feeds RSS diretos (PRIORITÁRIOS). Pode haver mais de um feed.
#   - 'dominio': usado no FALLBACK via Google News (site:<dominio> when:Nh)
#     quando TODOS os feeds diretos falham ou estão vazios.
#
# Veículos sem RSS funcional recebem lista vazia em 'rss' — o sistema cai
# automaticamente no Google News como fallback.
# -----------------------------------------------------------------------------
VEICULOS = {
    "Valor Econômico": {
        "rss": ["https://www.valor.com.br/ultimas-noticias/feed"],
        "dominio": "valor.globo.com",
    },
    "Estadão": {
        "rss": ["https://www.estadao.com.br/feed/"],
        "dominio": "estadao.com.br",
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
    "CNN Brasil": {
        "rss": ["https://www.cnnbrasil.com.br/feed/"],
        "dominio": "cnnbrasil.com.br",
    },
    "Metrópoles": {
        "rss": ["https://www.metropoles.com/feed"],
        "dominio": "metropoles.com",
    },
    "Poder 360": {
        "rss": ["https://www.poder360.com.br/feed/"],
        "dominio": "poder360.com.br",
    },
    "InfoMoney": {
        "rss": ["https://www.infomoney.com.br/feed/"],
        "dominio": "infomoney.com.br",
    },
    "BR Investing": {
        "rss": [],
        "dominio": "br.investing.com",
    },
    "Estadão | Broadcast": {
        "rss": ["https://www.estadao.com.br/economia/feed/"],
        "dominio": "broadcast.com.br",
    },
    "Estadão | E-Investidor": {
        "rss": ["https://einvestidor.estadao.com.br/feed/"],
        "dominio": "einvestidor.estadao.com.br",
    },
    "Correio Braziliense": {
        "rss": [],
        "dominio": "correiobraziliense.com.br",
    },
    "Portal UOL": {
        "rss": ["https://rss.uol.com.br/feed/noticias.xml"],
        "dominio": "uol.com.br",
    },
    "Portal Exame": {
        "rss": ["https://exame.com/feed/"],
        "dominio": "exame.com",
    },
    "Veja": {
        "rss": [],
        "dominio": "veja.abril.com.br",
    },
    "Brazil Journal": {
        "rss": ["https://braziljournal.com/feed"],
        "dominio": "braziljournal.com",
    },
    "NeoFeed": {
        "rss": ["https://neofeed.com.br/feed/"],
        "dominio": "neofeed.com.br",
    },
    "Agência Brasil": {
        "rss": ["https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml"],
        "dominio": "agenciabrasil.ebc.com.br",
    },
}


GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419"


# -----------------------------------------------------------------------------
# BUSCA INTERNA DOS VEÍCULOS ("LUPA")
# -----------------------------------------------------------------------------
# Portais com busca server-side (WordPress) — o ScraperEngine consulta
# o endpoint de busca pelas entidades prioritárias + termos regulatórios.
# Portais com busca JavaScript (Valor, Estadão, Globo, CNN, Metrópoles)
# não entram aqui — seguem no fallback Google News.
# -----------------------------------------------------------------------------
BUSCA_SITES = {
    "NeoFeed": {
        "url": "https://neofeed.com.br/?s={termo}&feed=rss",
        "tipo": "wp",
    },
    "Brazil Journal": {
        "url": "https://braziljournal.com/?s={termo}&feed=rss",
        "tipo": "wp",
    },
}

# Termos consultados na busca direcionada (Lupa).
BUSCA_TERMOS = [
    "ABRASCA",
    "CVM",
    "Mercado de capitais",
    "IPO",
    "Governança corporativa",
    "Oferta pública",
    "Tag along",
    "Assembleia geral",
    "Capital aberto",
    "Tokenização",
    "B3",
]

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

# Se o RSS DIRETO do veículo entregar >= este nº de notícias DENTRO da janela,
# a camada de busca por termo (site:<domínio> "<TERMO>" when:Nh) é PULADA.
GN_SKIP_TERMO_ATE_ITENS = 6


# -----------------------------------------------------------------------------
# ENTIDADES-ALVO (CLIENTES) — Nível 1
# -----------------------------------------------------------------------------
# ABRASCA: Associação Brasileira das Companhias Abertas.
# Representante / Porta-voz Principal: Cátilo Cândido.
# Variações incluem grafias sem acento para captura robusta.
# -----------------------------------------------------------------------------
CLIENTES = {
    "ABRASCA": [
        "ABRASCA",
        "Associação Brasileira das Companhias Abertas",
        "Cátilo Cândido",
        "Catilo Candido",
    ],
}


# -----------------------------------------------------------------------------
# NÍVEL 2: CHAVES COMPOSTAS (Cenário Macro e Regulatório)
# -----------------------------------------------------------------------------
# Termos institucionais/regulatórios e macroeconômicos essenciais para o
# monitoramento de Mercado de Capitais. Inclui:
#   - Reguladores e ambientes de negociação (CVM, Otto Lobo, B3, bolsa, SEC,
#     NYSE, Nasdaq)
#   - Operações de mercado (IPO, Follow-on, OPA, Novo Mercado, listagem)
#   - Termos técnicos (tokenização, governança, reporting, ESG)
#   - MACROECONOMIA e política econômica (juros/Selic, fiscal/Orçamento,
#     reforma tributária, PIB/crescimento, crédito, Open Finance, câmbio) —
#     conforme a cobertura abrangente dos resumos entregues ao cliente.
# Ao encontrar QUALQUER um deles, a matéria é marcada como relevante com
# CLIENTES_CITADOS = [] (vazio).
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# NÍVEL 2 — CHAVES DE MONITORAMENTO INSTITUCIONAL (dois níveis)
# -----------------------------------------------------------------------------
# Para conter falso-positivo, o Nível 2 foi dividido em DOIS níveis de
# exigência:
#
#   CHAVES_NIVEL2_FORTES  -> termos INEQUÍVOCOS de mercado de capitais /
#                            regulação (CVM, B3, IPO, governança...).
#                            Apareceram = aprovou (sozinhos bastam).
#
#   CHAVES_NIVEL2_MACRO   -> termos MACROECONÔMICOS amplos (Selic, PIB,
#                            inflação, fiscal, orçamento, câmbio...). Aprova
#                            APENAS se também houver (no título/resumo OU no
#                            corpo) uma ÂNCORA de mercado de capitais
#                            (config.TERMOS_COOCORRENCIA_CAPITAIS) — senão um
#                            artigo político que cita "orçamento" uma vez
#                            poluiria o clipping.
#
#   CHAVES_NIVEL2_ESTRITAS -> termos de política econômica que o cliente quer
#                            monitorar SÓ quando tiverem relação direta com o
#                            ambiente de negócios (escala 6x1, jornada, Pix,
#                            reforma trabalhista...). NUNCA aprovam sozinhos:
#                            exigem âncora de mercado de capitais, mesmo no
#                            título.
# -----------------------------------------------------------------------------
CHAVES_NIVEL2_FORTES = [
    # ---- Reguladores e ambientes de negociação ----
    "CVM",
    "Comissão de Valores Mobiliários",
    "Otto Lobo",
    "B3",
    "Bolsa de Valores",
    "SEC",
    "U.S. Securities and Exchange Commission",
    "NYSE",
    "Nasdaq",
    "Novo Mercado",
    # ---- Operações de mercado de capitais ----
    "Oferta Pública",
    "Oferta pública de aquisição",
    "OPA",
    "IPO",
    "Follow-on",
    "Mercado de Capitais",
    "Mercado de ações",
    "Mercado acionário",
    "Governança Corporativa",
    "Empresa de capital aberto",
    "Companhia aberta",
    "Capital aberto",
    "Tag along",
    "Assembleia Geral de Acionistas",
    "Relatório de administração",
    "Dividendos",
    "Juros sobre capital próprio",
    "Prospecto",
    "Registro de emissor",
    "Responsabilização de administradores",
    # ---- Termos técnicos / ativos digitais ----
    "Tokenização",
    "Tokenização de ativos",
    "Tokens",
    "Crowdfunding",
    "Ações preferenciais",
    "Ações ordinárias",
    "Listagem",
    "Securitização",
    "FIDC",
    "CRI",
    "CRA",
    "Fundos de investimento",
    "Liquidação extrajudicial",
]

CHAVES_NIVEL2_MACRO = [
    # ---- Regulatórios GERAIS (fora do contexto de companhias abertas,
    #      precisam de âncora) ----
    "Compliance",
    "Reporting",
    "Transparência",
    "ESG",
    "Prestação de contas",
    # ---- MACROECONOMIA: juros / monetário / câmbio ----
    "Selic",
    "Taxa de juros",
    "Copom",
    "Banco Central",
    "Política monetária",
    "Compactação de juros",
    "Swap cambial",
    "Câmbio",
    "Inflação",
    "IPCA",
    "Juros",
    # ---- MACROECONOMIA: fiscal / orçamento / tributário ----
    "Orçamento",
    "Orçamento de 2027",
    "Superávit",
    "Déficit",
    "Dívida pública",
    "Meta fiscal",
    "Reforma tributária",
    "Arrecadação",
    "Gastos públicos",
    "Ajuste fiscal",
    "Fiscal",
    # ---- MACROECONOMIA: crescimento / crédito / serviços financeiros ----
    "PIB",
    "Crescimento econômico",
    "Economia brasileira",
    "Produtividade",
    "Crédito",
    "Crédito garantido",
    "Open Finance",
    "Open Banking",
    "Cade",
]

CHAVES_NIVEL2_ESTRITAS = [
    "Escala 6x1",
    "Escala 6×1",
    "Reforma trabalhista",
    "Jornada de trabalho",
    "Pix",
]

# Lista combinada (para retrocompatibilidade com o pré-filtro do main.py e
# relatórios de diagnóstico). A aprovação SEMÂNTICA usa as três listas acima.
CHAVES_NIVEL2 = (
    CHAVES_NIVEL2_FORTES + CHAVES_NIVEL2_MACRO + CHAVES_NIVEL2_ESTRITAS
)


# -----------------------------------------------------------------------------
# NÍVEL 3: REDE DE ARRASTO + JARGÃO DE MERCADO
# -----------------------------------------------------------------------------
# Palavras amplas que disparam a rede de arrasto. Se uma matéria for pega
# APENAS por elas, precisa de coocorrência com o jargão de negócios.
PALAVRAS_ARRASTO = [
    "Mercado",
    "Ações",
    "Empresa",
    "Companhia",
    "Investimento",
    "Investidor",
    "Acionista",
    "Emissão",
    "Oferecimento",
]

# Jargão de Mercado de Capitais exigido na validação contextual (coocorrência).
JARGAO_NEGOCIOS = [
    "bolsa",
    "B3",
    "CVM",
    "mercado de capitais",
    "ofertas públicas",
    "IPO",
    "governança",
    "ações",
    "acionistas",
    "dividendos",
    "prospecto",
    "registro",
    "emitente",
    "companhia aberta",
    "capital aberto",
]

# Termos de Mercado de Capitais exigidos em COOCORRÊNCIA quando a aprovação
# viria apenas de palavras arrasto genéricas + jargão genérico.
TERMOS_COOCORRENCIA_CAPITAIS = [
    "mercado de capitais",
    "mercado de ações",
    "bolsa de valores",
    "B3",
    "ofertas públicas",
    "oferta pública",
    "IPO",
    "follow-on",
    "governança corporativa",
    "companhia aberta",
    "empresa de capital aberto",
    "listada em bolsa",
    "abertura de capital",
    "assembleia de acionistas",
    "cvm",
    "tag along",
    "ações preferenciais",
    "ações ordinárias",
    "registro de emissor",
    "conselho de administração",
]

# Arrastos "GENÉRICOS": comuns demais para, sozinhos, garantir contexto de
# mercado de capitais.
GENERIC_ARRASTO = ["Mercado", "Ações", "Empresa", "Companhia"]

# Jargões de negócios "FRACOS" (genéricos ou ambíguos). Incluem "ações",
# "registro", "emissão" e "bolsa" (que também significam "ações judiciais",
# "registro civil", "emissão de licença" e "Bolsa Família"): quando a matéria
# depende deles, exige-se coocorrência com termo inequívoco do mercado de
# capitais.
GENERIC_JARGAO = [
    "mercado",
    "empresa",
    "companhia",
    "investimento",
    "investidor",
    "governo",
    "ações",
    "acionistas",
    "registro",
    "emissão",
    "bolsa",
    "governança",
]

# Termos EXTRAS usados somente no PRÉ-FILTRO RÁPIDO (main.py).
PRE_FILTRO_TERMOS_BONUS = [
    "ação",
    "ações",
    "bolsa",
    "B3",
    "CVM",
    "IPO",
    "ofertas públicas",
    "governança",
    "acionista",
    "dividendos",
    "capital aberto",
    "mercado de capitais",
    "assembleia",
    "emissão de ações",
    "follow-on",
    "abertura de capital",
    "tokenização",
    # Macro complementar (o full-text é quem decide a relevância final)
    "juros",
    "selic",
    "inflação",
    "orçamento",
    "superávit",
    "deficit",
    "pib",
    "reforma tributária",
    "meta fiscal",
    "open finance",
    "crédito",
    "escala 6x1",
]

# -----------------------------------------------------------------------------
# ÂNCORA BRASIL (porta de entrada para feeds estrangeiros)
# -----------------------------------------------------------------------------
# Veículos de fora (ex.: BR Investing / Investing.com Brasil) trazem muito
# noticiário de empresas ESTRANGEIRAS (IPOs na NYSE/HK, fusões, SPACs...),
# que não interessa à ABRASCA (companhias abertas brasileiras). Para esses
# veículos, a matéria só é aceita se a superfície (título + resumo) citar o
# mercado brasileiro — por exemplo, empresa brasileira, B3/Ibovespa, CVM,
# real, "mercado brasileiro" etc.
TERMOS_ANCORA_BRASIL = [
    "brasil",
    "brasileira",
    "brasileiras",
    "brasileiro",
    "brasileiros",
    "b3",
    "bovespa",
    "ibovespa",
    "cvm",
    "bndes",
    "r$",
    "em reais",
    "de reais",
    "mercado brasileiro",
    "bolsa brasileira",
    "ação brasileira",
    "acoes brasileiras",
    "empresa brasileira",
    "companhia brasileira",
    "lei das s.a.",
]
# -----------------------------------------------------------------------------
# Porta de saída "ORIGEM ESTRANGEIRA" (gate global do pipeline):
# A ABRASCA acompanha companhias ABERTAS BRASILEIRAS. Matéria cujo TÍTULO
# marca origem ESTRANGEIRA (IPO da SpaceX, Shein em Hong Kong, Nvidia, LVMH,
# SEC dos EUA, Novartis, OpenAI...) é REPROVADA mesmo aprovada na matriz
# semântica, salvo se o mesmo TÍTULO nomear uma companhia brasileira
# (config.COMPANHIAS_ANCORA_BRASILEIRAS). O resumo não participa da regra —
# ele costuma citar NYSE/Nasdaq" de passagem em boas matérias brasileiras.
# Verificação por PALAVRA INTEIRA para indicadores de 1 termo.
# -----------------------------------------------------------------------------
INDICADORES_ORIGEM_ESTRANGEIRA = [
    "nasdaq",
    "nyse",
    "wall street",
    "s&p 500",
    "eua",
    "estados unidos",
    "asia",
    "toquio",
    "hong kong",
    "india",
    "africa",
    "europa",
    "europeia",
    "europeu",
    "chinesa",
    "chines",
    "china",
    "londres",
    "paris",
    "nova york",
    "sec",
    "hong kong",
    "canada",
    "alemã",
    "alemao",
    "japonesa",
    "japao",
]

# Companhias ESTRANGEIRAS conhecidas (nome no título → ruído para a ABRASCA,
# salvo se o título/resumo tiver âncora Brasil). Lista curada + manutenível.
COMPANHIAS_ESTRANGEIRAS_IGNORAR = [
    "spacex",
    "shein",
    "nvidia",
    "lvmh",
    "novartis",
    "openai",
    "anthropic",
    "rothschild",
    "stagwell",
    "enflame",
    "vodafone",
    "sony",
    "samsung",
    "tesla",
    "apple",
    "google",
    "alphabet",
    "meta",
    "microsoft",
    "amazon",
    "netflix",
    "disney",
    "intel",
    "amd",
    "nokia",
    "blackrock",
    "nasdaq",
    "vanguard",
    "skybridge",
    "arm holdings",
    "tsmc",
    "knightcap",
    "wework",
    "saaspocalypse",
    "coreweave",
    "telecom italia",
    "yellow cake",
    "ingram micro",
    "ares capital",
    "equinor",
    "sofi",
    "runway",
]

# Companhias BRASILEIRAS conhecidas: a presença de uma delas no título/resumo
# EXIME a matéria do gate de origem estrangeira (ex.: "Banco Inter desembarca
# na Argentina" é notícia de companhia brasileira, não estrangeira). Lista
# curada + manutenível, em formas estáveis (evita "inter" sozinho, que casaria
# com "internet"/"internacional").
COMPANHIAS_ANCORA_BRASILEIRAS = [
    "banco inter",
    "inter & co",
    "inter&co",
    "inter",
    "vale",
    "b3",
    "ibovespa",
    "petrobras",
    "banco do brasil",
    "bradesco",
    "itau",
    "itaú",
    "btg",
    "xp inc",
    "nu holdings",
    "nubank",
    "magazine luiza",
    "magalu",
    "copasa",
    "meliuz",
    "cpfl",
    "movida",
    "totvs",
    "renner",
    "assaí",
    "grupo pão de açúcar",
    "mrv",
    "cyrela",
    "eztec",
]
# -----------------------------------------------------------------------------
# Veículos dedicados ao mercado de capitais: o pré-filtro NUNCA descarta
# nenhuma matéria destes veículos (desde que dentro da janela temporal).
VEICULOS_DEDICADOS = set()

# Vocabulário alargado de entrada para os veículos de mídia GERAL.
TERMOS_ENTRADA_MIDIA_GERAL = [
    "bolsa",
    "ações",
    "B3",
    "CVM",
    "IPO",
    "oferta pública",
    "mercado de capitais",
    "governança",
    "acionista",
    "dividendos",
    "capital aberto",
    "companhia",
    "assembleia",
    "emissão de ações",
    "abertura de capital",
    "tokenização",
    # Macro complementar (decisão final sempre da matriz)
    "juros",
    "selic",
    "orçamento",
    "superávit",
    "reforma tributária",
    "pib",
    "inflação",
    "open finance",
    "crédito",
    "escala 6x1",
]


# -----------------------------------------------------------------------------
# NÍVEL 4: BLACKLIST DE AMBIGUIDADE
# -----------------------------------------------------------------------------
# Palavras que identificam matérias usando "mercado/ações/empresa/juros/
# orçamento/PIB" fora do contexto econômico-financeiro: esportes, saúde,
# astrologia, automóveis, entretenimento, crime, clima etc. Presença de
# QUALQUER dessas palavras FORÇA IS_RELEVANT = False (override sobre todas
# as etapas) e remove a matéria da fila imediatamente.
# -----------------------------------------------------------------------------
BLACKLIST = [
    # Esportes
    "futebol",
    "atleta",
    "partida",
    "campeonato",
    "tênis",
    "tenis",
    "golfe",
    "gol",
    "gols",
    "fórmula 1",
    "formula 1",
    "basquete",
    "voleibol",
    "natação",
    "natacao",
    "olímpiadas",
    "olimpiadas",
    # Saúde / bem-estar / fitness
    "física",
    "fisica de",
    "exercício físico",
    "exercicio fisico",
    "treino",
    "academia",
    "dieta",
    "nutrição",
    "nutricao",
    "calorias",
    "emagrecer",
    # Astrologia / espiritualidade / holístico
    "astrologia",
    "horóscopo",
    "horoscopo",
    "signos",
    "espiritual",
    "holístico",
    "holistico",
    "energia espiritual",
    "zen",
    "meditação",
    "meditacao",
    # Automóveis / mobilidade
    "automóvel",
    "automovel",
    "automóveis",
    "automoveis",
    "automotiva",
    "automotivo",
    "carro",
    "carros",
    "suv",
    "sedã",
    "sedan",
    "direção autônoma",
    "direcao autonoma",
    # Entretenimento / cultura / celebridades
    "novela",
    "big brother",
    "bbb",
    "celebridade",
    "famosos",
    "reality show",
    "show",
    "cinema",
    "filme de",
    "série de",
    "serie de",
    "música",
    "musica",
    "premiação",
    "premiacao",
    "moda",
    "maquiagem",
    "culinária",
    "culinaria",
    "receita de",
    # Crime / polícia (fora de contexto econômico)
    "homicídio",
    "homicidio",
    "assassinato",
    "latrocínio",
    "latrocinio",
    "tiroteio",
    "prisão em flagrante",
    "prisao em flagrante",
    # Clima / meteorologia
    "previsão do tempo",
    "previsao do tempo",
    "temperatura máxima",
    "temperatura maxima",
    "chuva forte",
    # Programas sociais / políticas públicas que disparam falso "bolsa/ações"
    "bolsa família",
    "bolsa familia",
    # Litígio / justiça que alcança falso "ações"
    "ações judiciais",
    "acoes judiciais",
    "ação judicial",
    "acao judicial",
    # Política-policialesco e turismo (falsos "mercado/ações/governança")
    "carnaval",
    "turismo",
    "igreja",
    # Crise institucional / segurança pública sem mercado (falso "ações/justiça")
    "diretor-geral da polícia federal",
    "diretor-geral da pf",
    "afastamento de diretor-geral",
    # Bolsas de estudo / acadêmico (falso "bolsa" do mercado)
    "bolsa de estudo",
    "bolsas de estudo",
    "bolsista",
    # Séries/marcas de consumo que disparam falsos "mercado/ações"
    "bolsa de valores de brinquedo",
]


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
# FORMATAÇÃO DO RELATÓRIO
# -----------------------------------------------------------------------------
TITULO_DOCUMENTO = "📈 Resumo de Mercado de Capitais"
DATA_FORMATO = "%d de %B de %Y"
ARQUIVO_FORMATO = "Clipping_MercadoCapitais_{:%Y-%m-%d_%Hh%M}.docx"
