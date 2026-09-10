# =============================================================================
# config.py
# ---------
# Arquivo de configuração central do "Motor de Busca e Clipping de Notícias
# do Setor Elétrico".
#
# Este módulo concentra TODAS as constantes e estruturas de dados usadas pelo
# sistema: caminho de saída, lista dos 18 veículos com seus feeds RSS, as 7
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
# Todos os cálculos de janela temporal (data_limite) e as datas exibidas no
# relatório usam o horário de Brasília (America/Sao_Paulo). O Brasil não adota
# horário de verão desde 2019, então UTC-3 fixo é o valor correto atual.
#
# Usamos zoneinfo (banco IANA) quando disponível; em Windows sem o pacote
# 'tzdata', caímos para o offset fixo UTC-3 — equivalente hoje a Brasília.
try:
    from zoneinfo import ZoneInfo

    FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")
except Exception:  # noqa: BLE001  (ZoneInfoNotFoundError, module ausente etc.)
    FUSO_BRASILIA = datetime.timezone(datetime.timedelta(hours=-3))


def agora_brasilia():
    """
    Retorna o momento atual como datetime NAIVE no horário de Brasília.
    Datetimes naive em horário de Brasília são o padrão do sistema inteiro
    (fáceis de comparar e formatar).
    """
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .astimezone(FUSO_BRASILIA)
        .replace(tzinfo=None)
    )


def para_brasilia(dt):
    """
    Converte qualquer datetime (aware ou naive) para datetime NAIVE no
    horário de Brasília. Datetimes já naive são assumidos estar em Brasília
    (padrão do sistema), então retornam inalterados.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt  # Já assumido como horário de Brasília.
    return dt.astimezone(FUSO_BRASILIA).replace(tzinfo=None)


# -----------------------------------------------------------------------------
# CAMINHOS DE SAÍDA
# -----------------------------------------------------------------------------
# Detecta automaticamente o usuário do Windows e constrói o caminho absoluto
# onde o relatório .docx será salvo:
#   C:\Users\[NOME_DO_USUARIO]\Desktop\Instainfo Resumos - Entregas\Energia
# A variável de ambiente USERPROFILE no Windows contém o diretório do usuário.
# -----------------------------------------------------------------------------
USER_PROFILE = os.environ.get("USERPROFILE", os.path.expanduser("~"))
BASE_DIR = os.path.join(USER_PROFILE, "Desktop", "Instainfo Resumos - Entregas", "Energia")

# -----------------------------------------------------------------------------
# ORGANIZAÇÃO DAS ENTREGAS EM PASTAS
# -----------------------------------------------------------------------------
# A pasta de entrega fica dentro do projeto:
#   C:\Users\[USUARIO]\Desktop\Instainfo Resumos - Entregas\Energia\Resumos diários - Energia
# E dentro dela as entregas são organizadas por tipo:
#   Relatórios\  -> Clipping_Energia_<data>_<hora>.docx
#   Logs\        -> execucao.log (rastro das execuções do pipeline)
# -----------------------------------------------------------------------------
DIR_RESUMOS = os.path.join(BASE_DIR, "Resumos diários - Energia")
DIR_RELATORIOS = os.path.join(DIR_RESUMOS, "Relatórios")
# Relatórios antigos são movidos para "Relatórios\Arquivo" a cada execução
# (mantém a pasta de entrega só com a entrega mais recente).
DIR_ARQUIVO = os.path.join(DIR_RELATORIOS, "Arquivo")
DIR_LOGS = os.path.join(DIR_RESUMOS, "Logs")
ARQUIVO_LOG = os.path.join(DIR_LOGS, "execucao.log")

# Nº máximo de logs arquivados mantidos na pasta Logs (rotação do main.py).
MAX_LOGS_ARQUIVADOS = 10

# -----------------------------------------------------------------------------
# SAÚDE DOS FEEDS (registro por veículo + alerta)
# -----------------------------------------------------------------------------
# A cada run registra, para cada veículo, se os feeds entregaram matérias na
# janela (ok/vazio/falhou) e mantém histórico em JSON. Se um veículo ficar
# sem matérias por FEED_ALERTA_RUNS_SEM_MATERIA runs consecutivos, um alerta
# é logado (provável feed morto / bloqueio permanente).
ARQUIVO_SAUDE_FEEDS = os.path.join(DIR_LOGS, "saude_feeds.json")
FEED_ALERTA_RUNS_SEM_MATERIA = 3
SAUDE_RUNS_MAXIMO = 30

# -----------------------------------------------------------------------------
# CACHE DE FULL-TEXT (confiabilidade / determinismo)
# -----------------------------------------------------------------------------
# Cache persistente chaveado pela URL ORIGINAL da notícia: ao reencontrar a
# MESMA url num run posterior, o pipeline reutiliza o texto já baixado e a
# data de publicação extraída — determinismo TOTAL entre execuções e menos
# pressão anti-bot sobre os portais. Desativável via --sem-cache.
DIR_CACHE = os.path.join(DIR_RESUMOS, "Cache")
ARQUIVO_CACHE_FULLTEXT = os.path.join(DIR_CACHE, "fulltext.json")

# Tamanho máximo do cache (evita crescimento infinito; a entrada mais antiga
# é removida quando o teto é atingido — a dict mantém ordem de inserção).
CACHE_MAX_ENTRADAS = 4000

# A cada N novas entradas o cache é gravado em disco (persistência parcial em
# caso de falha/queda), além da gravação final no fim do pipeline.
CACHE_FLUSH_A_CADA = 50

# Se por algum motivo o Desktop não for encontrado (ex.: usuário com OneDrive que
# move o Desktop), tentamos descobrir via PowerShell. Caso contrário, mantém o
# caminho padrão. Esse fallback é resolvido em tempo de execução pelo exporter.
# Aqui apenas definimos a constante base.


# -----------------------------------------------------------------------------
# TIMEOUT PADRÃO (segundos)
# -----------------------------------------------------------------------------
# Usado em TODOS os requests (RSS, scraping HTML e API do IS.GD).
# Conforme especificado no Capítulo 7, o padrão é timeout=10.
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
# Padrão de horas passadas para a busca (ex.: últimas 24h ou 48h).
# O usuário pode sobrescrever via CLI.
# -----------------------------------------------------------------------------
DEFAULT_HOURS = 24


# -----------------------------------------------------------------------------
# RODÍZIO DE USER-AGENTS (Bypass de Paywall / Anti-bot)
# -----------------------------------------------------------------------------
# Para lidar com paywalls (Valor, Globo, Estadão) e proteções anti-bot,
# o sistema rotaciona uma lista de User-Agents reais a cada requisição.
# -----------------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


# -----------------------------------------------------------------------------
# VEÍCULOS (18 FONTES)
# -----------------------------------------------------------------------------
# Dicionário mapeando cada veículo a seus feeds RSS e ao domínio de busca.
#
# Estratégia de coleta (Capítulo 2):
#   - 'rss': lista de feeds RSS diretos (PRIORITÁRIOS). Pode haver MAIS DE UM
#     feed por veículo (ex.: Folha) — todos são coletados e mesclados.
#   - 'dominio': usado no FALLBACK via Google News (site:<dominio> when:Nh)
#     quando TODOS os feeds diretos falham ou estão vazios. Isso cobre veículos
#     com feeds mortos, protegidos por Cloudflare ou com paywall (Valor,
#     Estadão, Globo, CanalEnergia, etc.).
#
# Nota importante: a resiliência é o coração do sistema. Se um feed falhar,
# o sistema loga o erro e continua para o próximo veículo (Capítulo 7), sem
# interromper o fluxo. O fallback Google News entra automaticamente.
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
    "Estadão | Broadcast": {
        "rss": ["https://www.estadao.com.br/economia/feed/"],
        "dominio": "broadcast.com.br",
    },
    "NeoFeed": {
        "rss": ["https://neofeed.com.br/feed/"],
        "dominio": "neofeed.com.br",
    },
    "Brazil Journal": {
        "rss": ["https://braziljournal.com/feed"],
        "dominio": "braziljournal.com",
    },
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
    "Metrópoles": {
        "rss": ["https://www.metropoles.com/feed"],
        "dominio": "metropoles.com",
    },
    "CNN Brasil": {
        "rss": ["https://www.cnnbrasil.com.br/feed/"],
        "dominio": "cnnbrasil.com.br",
    },
    "Agência iNFRA": {
        "rss": ["https://agenciainfra.com/blog/feed/"],
        "dominio": "agenciainfra.com",
    },
    "Cenário Energia": {
        "rss": ["https://cenarioenergia.com.br/feed/"],
        "dominio": "cenarioenergia.com.br",
    },
    "Poder 360": {
        "rss": ["https://www.poder360.com.br/feed/"],
        "dominio": "poder360.com.br",
    },
    "Canal Solar": {
        "rss": ["https://canalsolar.com.br/feed/"],
        "dominio": "canalsolar.com.br",
    },
    "Portal UOL": {
        "rss": ["https://rss.uol.com.br/feed/noticias.xml"],
        "dominio": "uol.com.br",
    },
}


GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419"


# -----------------------------------------------------------------------------
# BUSCA INTERNA DOS VEÍCULOS ("LUPA") — ESTRATÉGIA HÍBRIDA
# -----------------------------------------------------------------------------
# Além da varredura por RSS (Broad Crawl), o ScraperEngine consulta a BUSCA
# INTERNA de cada portal (Targeted Search) para capturar matérias por entidade
# e termos regulatórios que não estão na capa/feed, com LINKS DO PRÓPRIO SITE
# (sem redirects do Google News).
#
# Estrutura por veículo:
#   "url"  : template com {termo}, ex: https://site/?s=ABRADEE
#   "tipo" : "wp"  -> WordPress: `&feed=rss` devolve RSS dos resultados
#                    (com data de publicação — ideal). Se falhar, cai no HTML.
#            "html"-> busca só por HTML (sem feed de resultados).
#   "html_fallback": permite tentar a página HTML quando o feed de resultados
#                    vier vazio (padrão: True).
#
# São indexados apenas portais com busca server-side (WordPress ). Portais
# com busca JavaScript (Valor, Estadão, Globo, CNN, Metrópoles) não entram
# aqui — seguem no fallback Google News.
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
    "Agência iNFRA": {
        "url": "https://agenciainfra.com/blog/?s={termo}&feed=rss",
        "tipo": "wp",
    },
    "Agência Eixos": {
        "url": "https://www.eixos.com.br/?s={termo}&feed=rss",
        "tipo": "wp",
    },
    "CanalEnergia": {
        "url": "https://www.canalenergia.com.br/?s={termo}&feed=rss",
        "tipo": "wp",
    },
}

# Termos consultados na busca direcionada (Lupa): as 7 entidades prioritárias
# + termos regulatórios críticos determinados pelo cliente.
BUSCA_TERMOS = [
    "ABRADEE",
    "ABIAPE",
    "ABEEólica",
    "ABRAGE",
    "ABiogás",
    "Renova Energia",
    "ABRATE",
    "Leilão de Reserva",
    "Leilão de energia",
    "Bandeira Tarifária",
    "Curtailment",
    "ANEEL",
]

# Limite de resultados mantidos por termo de busca (após o filtro de tempo).
BUSCA_MAX_POR_TERMO = 8

# Nº de threads na análise paralela do full-text (maior gargalo de rede).
# 6 é equilibrado: acelera muito sem parecer ataque (anti-bot) a um domínio.
ANALISE_WORKERS = 6

# Nº de workers na COLETA paralela dos veículos (fase 100% I/O de rede).
# 6 agiliza a varredura ampla (RSS + Lupa + busca direcionada + fallback)
# para ~1 minuto; os timeouts por request (config.TIMEOUT) impedem que um
# site lento segure a esteira inteira.
COLETA_WORKERS = 6

# Nº de respostas 429/503 consecutivas do Google News que ativam o
# circuit-breaker (desativa as camadas Google News no restante do run).
GN_MAX_FALHAS_SEGUIDAS = 4

# Jitter (segundos) aplicado ANTES de cada requisição AO Google News
# (feeds de busca e decodificação de links). O Google aplica rate-limit 503
# por IP quando recebe rajadas; um pequeno intervalo aleatório entre as
# consultas evita a rajada. As consultas GN também são SERIALIZADAS
# (executadas em worker único), enquanto RSS direto / páginas seguem em
# paralelo.
GN_JITTER_MIN = 0.8
GN_JITTER_MAX = 1.8

# Cooldown ADAPTATIVO do Google News: após uma resposta 429/503, a espera da
# PRÓXIMA consulta GN é dobrada (GN_JITTER_FATOR) vezes o valor atual, sem
# nunca ultrapassar GN_JITTER_TETO. Em sucesso, a espera "desce" lentamente
# multiplicada por GN_JITTER_RECUPERACAO — nunca abaixo de GN_JITTER_MIN.
GN_JITTER_FATOR = 2.0
GN_JITTER_TETO = 8.0
GN_JITTER_RECUPERACAO = 0.7

# Redução de dependência do Google News (item 3): se o RSS DIRETO do veículo
# entregar pelo menos este nº de notícias DENTRO da janela, a camada de busca
# direcionada por termo (site:<domínio> "<TERMO>" when:Nh) é PULADA para este
# veículo — o feed direto já cobre a pauta e a busca focada quase só
# reproduziria o mesmo conteúdo (com risco extra de 503). Veículos com feed
# fraco/bloqueado continuam usando o Google News para não perder recall.
GN_SKIP_TERMO_ATE_ITENS = 6


# -----------------------------------------------------------------------------
# ENTIDADES-ALVO (7 CLIENTES)
# -----------------------------------------------------------------------------
# Nomes exatos (buscados case-insensitive) usados no Nível 1 da filtragem.
# Cada entrada contém o nome oficial exibido no relatório e as variações
# de busca (para capturar siglas, grafias alternativas e nome de líderes).
# -----------------------------------------------------------------------------
CLIENTES = {
    "ABRADEE": [
        "ABRADEE",
        "Associação Brasileira de Distribuidores de Energia Elétrica",
        "Patricia Audi",
        "Patrícia Audi",
    ],
    "ABIAPE": [
        "ABIAPE",
        "Associação Brasileira dos Investidores em Autoprodução de Energia",
        "Mário Menel",
        "Mario Menel",
    ],
    "ABEEólica": [
        "ABEEólica",
        "ABEEolica",
        "Associação Brasileira de Energia Eólica",
        "Élbia Gannoum",
        "Elbia Gannoum",
    ],
    "ABRAGE": [
        "ABRAGE",
        "Associação Brasileira das Empresas Geradoras de Energia Elétrica",
        "Marisete Fátima Dadald Pereira",
        "Marisete Dadald",
    ],
    "ABiogás": [
        "ABiogás",
        "ABiogas",
        "Associação Brasileira do Biogás",
        "Alessandro Gardemann",
    ],
    "Renova Energia": [
        "Renova Energia",
        "Sandro Yamamoto",
    ],
    "ABRATE": [
        "ABRATE",
        "Associação Brasileira das Empresas de Transmissão de Energia Elétrica",
    ],
}


# -----------------------------------------------------------------------------
# NÍVEL 2: CHAVES COMPOSTAS (Cenário Macro e Regulatório)
# -----------------------------------------------------------------------------
# Buscadas quando nenhum cliente é encontrado diretamente no Nível 1.
# São termos institucionais/regulatórios essenciais para o monitoramento.
# Ao encontrar QUALQUER um deles, a matéria é marcada como relevante com
# CLIENTES_CITADOS = [] (vazio), pois o conteúdo é de interesse macro, mesmo
# sem citar um cliente específico.
# -----------------------------------------------------------------------------
CHAVES_NIVEL2 = [
    "ANEEL",
    "MME",
    "Ministério de Minas e Energia",
    "ONS",
    "CCEE",
    "Mercado Livre de Energia",
    "Consumidor Livre",
    "Leilão de energia",
    "Leilão de reserva",
    "Leilão de transmissão",
    "Bandeira Tarifária",
    "Tarifas de energia",
    "Curtailment",
    "cortes de geração",
    "Transição Energética",
    "Geração Distribuída",
    "GD",
    "Crise Hídrica",
    "GSF",
    "risco hidrológico",
    "Data Centers",
    "Redata",
    "Energias Renováveis",
    "Biometano",
    "Marco Regulatório",
    "Licenciamento Ambiental",
]


# -----------------------------------------------------------------------------
# NÍVEL 3: REDE DE ARRASTO (Palavras amplas) + Jargão de Negócios
# -----------------------------------------------------------------------------
# Palavras únicas e amplas que disparam a rede de arrasto. Se uma matéria for
# pega APENAS por elas, precisa passar pela DUPLA VALIDAÇÃO CONTEXTUAL:
# o texto deve conter também termos do jargão de negócios (coocorrência).
# -----------------------------------------------------------------------------
PALAVRAS_ARRASTO = [
    "Energia",
    "Distribuidoras",
    "Elétrica",
    "Elétrico",
    "Eólica",
    "Solar",
]

# Jargão de negócios exigido na validação contextual (coocorrência).
JARGAO_NEGOCIOS = [
    "setor",
    "governo",
    "investimento",
    "mercado",
    "tarifas",
    "MW",
    "B3",
    "regulamentação",
    "regulacao",
    "geração",
    "transmissão",
    "leilão",
    "agência",
]

# Termos do SETOR ELÉTRICO exigidos em COOCORRÊNCIA quando a aprovação
# viria apenas de palavras ARRASTO genéricas + jargão de negócios genérico.
#
# Motivação: "energia", "elétrica"/"elétrico" e jargões como "setor",
# "governo", "mercado", "investimento" e "tarifa" aparecem em matérias de
# comércio exterior, agronegócio, resgates, esporte etc. (ex.: "exportações
# da Itália", "usina hidrelétrica em túnel no Nepal"). Para que Nível 3
# aprove usando SÓ essas palavras, é obrigatório que um termo inequívoco do
# setor elétrico também apareça no texto.
TERMOS_COOCORRENCIA_SETOR_ELETRICO = [
    "tarifa de energia",
    "tarifas de energia",
    "bandeira tarifária",
    "bandeira tarifaria",
    "conta de luz",
    "consumidor",
    "consumidores",
    "aneel",
    "distribuidora",
    "distribuidoras",
    "mercado livre de energia",
    "reajuste",
    "subsídio cruzado",
    "subsidio cruzado",
    "tarifa social",
    "eletricidade",
    "setor elétrico",
    "setor eletrico",
    "energia elétrica",
    "energia eletrica",
    "linha de transmissão",
    "linhas de transmissão",
    "linha de transmissao",
    "redes de transmissão",
    "capacidade instalada",
    "geração de energia",
    "geracao de energia",
]

# Alias de compatibilidade (a guarda da 'tarifa' usa o mesmo vocabulário).
TARIFA_ELETRICO_COOCORRENCIA = TERMOS_COOCORRENCIA_SETOR_ELETRICO

# Arrastos "GENÉRICOS": comuns demais para, sozinhos, garantir contexto do
# setor elétrico (ex.: "Elétrica" casa por substring com "hidrelétrica").
# Quando a aprovação do Nível 3 depender deles + jargão genérico, exige-se
# coocorrência com TERMOS_COOCORRENCIA_SETOR_ELETRICO.
GENERIC_ARRASTO = ["Energia", "Elétrica", "Elétrico"]

# Jargões de negócios "FRACOS" (genéricos): não garantem setor elétrico.
# Jargões fortes ("geração", "transmissão", "MW", "leilão"...) continuam
# aprovando sozinhos, pois já são vocabulário do setor.
GENERIC_JARGAO = [
    "setor",
    "governo",
    "investimento",
    "mercado",
    "tarifas",
    "regulamentação",
    "regulacao",
    "agência",
]

# Termos EXTRAS usados somente no PRÉ-FILTRO RÁPIDO (main.py).
# O pré-filtro é um superconjunto do filtro final: a simples presença de um
# destes termos no título/resumo mantém a matéria como candidata à avaliação
# completa (full-text). A decisão de relevância NUNCA é tomada por estes
# termos — ela pertence à matriz final (Níveis 1 a 4).
PRE_FILTRO_TERMOS_BONUS = [
    "geração",
    "geracao",
    "transmissão",
    "transmissao",
    "distribuição de energia",
    "hidrelétrica",
    "hidreletrica",
    "termoelétrica",
    "termoeletrica",
    "usina",
    "subestação",
    "subestacao",
    "eletricidade",
    "consumidor de energia",
    "autoprodução",
    "autoproducao",
    "biogás",
    "biogas",
    "biometano",
    "linhas de transmissão",
    "rede elétrica",
    "rede eletrica",
]

# -----------------------------------------------------------------------------
# CAPTURA ALARGADA DO PRÉ-FILTRO (precisão por veículo)
# -----------------------------------------------------------------------------
# VEÍCULOS DEDICADOS AO SETOR ELÉTRICO: o pré-filtro NUNCA descarta nenhuma
# matéria destes veículos (desde que dentro da janela temporal). Tudo o que
# publicarem passa para o scraping do full-text e para a matriz semântica — a
# decisão final de relevância continua pertencendo à matriz (Níveis 1 a 4).
VEICULOS_ENERGIA = {
    "CanalEnergia",
    "MegaWhat",
    "Cenário Energia",
    "Canal Solar",
    "Brasil Energia",
    "Agência Eixos",
}

# VOCABULÁRIO ALARGADO DE ENTRADA para os veículos de mídia GERAL (Folha,
# Estadão, Valor, O Globo, Metrópoles, UOL, CNN, Poder 360...): se o título ou
# a descrição contiver QUALQUER destes termos, a matéria passa imediatamente
# para a avaliação full-text (a matriz continua sendo o juiz final).
TERMOS_ENTRADA_MIDIA_GERAL = [
    "luz",
    "tarifa",
    "apagão",
    "usina",
    "hidrelétrica",
    "hidreletrica",
    "solar",
    "vento",
    "eólica",
    "eolica",
    "subsídio",
    "subsidio",
    "conta de luz",
    "geração",
    "geracao",
]


# -----------------------------------------------------------------------------
# NÍVEL 4: BLACKLIST DE AMBIGUIDADE
# -----------------------------------------------------------------------------
# Palavras que identificam matérias de Esportes, Saúde e Astrologia usando
# "energia" fora do contexto do setor elétrico. Presença de QUALQUER dessas
# palavras FORÇA IS_RELEVANT = False (override sobre todas as etapas)
# e remove a matéria da fila imediatamente.
# -----------------------------------------------------------------------------
BLACKLIST = [
    "física",
    "fisica",
    "espiritual",
    "treino",
    "disposição",
    "disposicao",
    "astrologia",
    "futebol",
    "atleta",
    "calorias",
    "holístico",
    "holistico",
    "signos",
    "partida",
    # Domínio automotivo: "elétrica / híbrido / energia / mercado" nesse
    # contexto falam de CARROS, não do setor elétrico. Presença de qualquer
    # termo força is_relevante=False (override).
    "automóvel",
    "automovel",
    "automóveis",
    "automoveis",
    "automotiva",
    "automotivo",
    "automotiva",
    "carro",
    "carros",
    "suv",
    "sedã",
    "sedan",
    "motor à combustão",
    "motor a combustão",
    "combustão interna",
    "combustao interna",
]


# -----------------------------------------------------------------------------
# CONFIGURAÇÃO DOS ENCURTADORES DE LINK (IS.GD → TinyURL → URL original)
# -----------------------------------------------------------------------------
# O LinkShortener usa a lógica exata de failover e validação dupla:
#   1) Tentativa principal: IS.GD (formato JSON, chave 'shorturl').
#   2) Failover automático: TinyURL (texto puro).
#   3) Validação dupla obrigatória (requests.head) do link curto.
#   4) Se tudo falhar, retorna a URL longa original — jamais um link quebrado.
#
# Timeouts conforme especificação do módulo de encurtamento: 5 segundos em
# cada etapa (API IS.GD, API TinyURL e validação HEAD).
#   JSON: https://is.gd/create.php?format=json&url=<URL_CODIFICADA>
#   TinyURL plain-text: https://tinyurl.com/api-create.php?url=<URL_CODIFICADA>
# -----------------------------------------------------------------------------
ISGD_API_URL = "https://is.gd/create.php"
ISGD_TIMEOUT = 5

TINYURL_API_URL = "https://tinyurl.com/api-create.php"
TINYURL_TIMEOUT = 5

# Timeout da validação dupla (requests.head / requests.get leve) do link curto.
VALIDATION_TIMEOUT = 5

# Status HTTP considerados VÁLIDOS na validação dupla: qualquer status < 400
# (200 OK, 301/302 redirect válido, 304 etc.).
STATUS_VALIDO_MAX = 400


# -----------------------------------------------------------------------------
# FORMATAÇÃO DO RELATÓRIO
# -----------------------------------------------------------------------------
# Cabeçalho fixo do documento. O conteúdo é estritamente controlado no
# WordExporter, mas as strings ficam aqui para single-source-of-truth.
# -----------------------------------------------------------------------------
TITULO_DOCUMENTO = "⚡ Resumo de Energia"
DATA_FORMATO = "%d de %B de %Y"
ARQUIVO_FORMATO = "Clipping_Energia_{:%Y-%m-%d_%Hh%M}.docx"
