# =============================================================================
# scraper.py
# ----------
# Módulo ScraperEngine: responsável pela coleta de dados dos 18 veículos de
# Mercado de Capitais.
#
# Estratégia HÍBRIDA de coleta (varreduras + fallback + desduplicação):
#   1) BROAD CRAWL (RSS/Últimas notícias): monitora o feed do veículo para
#      capturar a pauta geral do mercado de capitais na janela de tempo.
#   2) TARGETED SEARCH (BUSCA INTERNA/"LUPA"): para portais com busca
#      server-side (WordPress), consulta o endpoint de busca pelas entidades
#      prioritárias + termos regulatórios. Links do PRÓPRIO SITE.
#   3) TARGETED SEARCH VIA GOOGLE NEWS: para portais de ECONOMIA GERAL sem
#      busca consultável (Folha, Estadão, Valor, Metrópoles, UOL...), consultas
#      focadas site:<dominio> "<TERMO>" when:Nh capturam matérias sobre os
#      clientes que não chegam à capa/feed.
#   4) FALLBACK GOOGLE NEWS: último recurso (site:<dominio> when:Nh) quando o
#      RSS direto E as buscas não trouxerem nada.
#   5) DESDUPLICAÇÃO: matérias achadas em mais de uma via entram UMA única vez
#      (URL canônica + título normalizado).
#   6) Enriquecimento do texto completo: acessa a URL original e extrai os
#      <p> (parágrafos) do corpo via newspaper3k (com fallback para BS4).
#
# REGRA CRÍTICA DE ENGENHARIA — FILTRO TEMPORAL (Publicação Original):
#   O corte de tempo (24h/48h/Xh) considera EXCLUSIVAMENTE a DATA DE
#   PUBLICAÇÃO ORIGINAL, sempre no HORÁRIO DE BRASÍLIA.
#     - No RSS/Atom: usa apenas 'published' / 'published_parsed'.
#       Ignora totalmente 'updated' / 'updated_parsed'.
#     - No scraping HTML: extrai 'article:published_time', Schema.org
#       'datePublished' ou <time datetime> de publicação.
#       Ignora 'article:modified_time' / 'dateModified'.
#   Matérias antigas apenas ATUALIZADAS (published antigo) são DESCARTADAS.
#   Matéria sem data de publicação original confirmada é descartada, pois
#   não pode ser validada contra a janela de tempo.
#
# Resiliência (Capítulo 7):
#   - Todo request tem timeout e bloco try/except.
#   - Se um veículo falhar, loga o erro e segue para o próximo, sem interromper
#     o loop principal.
#
# Bypass de paywall / anti-bot:
#   - Rodízio de User-Agents reais a cada request.
#   - Headers aceitando text/html.
# =============================================================================

import datetime
import json
import logging
import os
import random
import re
import socket
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import feedparser
from bs4 import BeautifulSoup

import config

# Configuração de logging do módulo (console).
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class ScraperEngine:
    """Motor de coleta de notícias dos 18 veículos de comunicação."""

    # ------------------------------------------------------------------
    # CONSTRUTOR
    # ------------------------------------------------------------------
    def __init__(self, horas_passadas=config.DEFAULT_HOURS, data_limite_max=None, data_limite=None, sem_cache=False):
        """
        Inicializa o motor de scraping.

        Parâmetros:
            horas_passadas (int): janela de tempo (horas) para filtrar as
                                  notícias. Padrão = 24.
            data_limite_max (datetime | None): LIMITE SUPERIOR da janela
                                  (fim do intervalo). Usado no modo calendário
                                  (--de/--ate): só publicações até data_limite_max
                                  entram (ex.: "04/09 a 06/09" exclui o dia 07).
                                  None = sem limite superior (modo "últimas Nh").
            data_limite (datetime | None): LIMITE INFERIOR exato. Se informado
                                  (modo calendário), substitui o cálculo
                                  "agora - horas" — ex.: 04/09/2026 00:00.
            sem_cache (bool): se True, ignora o cache persistente de full-text
                                  (força novo scraping da mesma URL).
        """
        self.horas_passadas = horas_passadas
        self.data_limite_max = data_limite_max

        # Compute da data-limite: tudo publicado ANTES disso é descartado.
        # Ex.: agora - 24 horas = data_limite.
        # REGRAS DE HORÁRIO: toda a janela é calculada no HORÁRIO DE BRASÍLIA
        # (config.FUSO_BRASILIA), independente do fuso da máquina.
        self.data_limite = config.agora_brasilia() - datetime.timedelta(
            hours=horas_passadas
        )
        if data_limite is not None:
            self.data_limite = data_limite
        self.user_agent_index = 0  # Índice para o rodízio de User-Agents.

        # Controle de desduplicação (RSS + busca interna + Google News):
        # evita que a mesma matéria (mesma URL ou mesmo título normalizado)
        # entre duas vezes no relatório vinda de vias diferentes.
        self._vistos_links = set()
        self._vistos_titulos = set()

        # Lock para a desduplicação: a coleta roda em PARALELO (ThreadPool),
        # então o registro de notícias compartilhado precisa de exclusão mútua
        # para garantir a unicidade mesmo com várias threads ao mesmo tempo.
        self._lock_dedupe = threading.Lock()

        # Circuit-breaker do Google News: quando o RSS do Google passa a
        # responder 429/503 (rate-limit/block por IP), após N falhas seguidas
        # as camadas Google News deixam de ser consultadas no restante do run,
        # e o pipeline segue com RSS direto + Lupa (WordPress) + enriquecimento.
        self._gn_falhas_seguidas = 0
        self._gn_bloqueado = False
        self._lock_gn = threading.Lock()

        # Serializador do TRÁFEGO do Google News (proteção contra rate-limit):
        # TODAS as requisições direcionadas ao Google News passam por este
        # lock (worker único + jitter aleatório entre consultas), enquanto os
        # feeds RSS diretos e as páginas dos portais seguem em PARALELO.
        self._lock_gn_fluxo = threading.Lock()

        # Lock do rodízio de User-Agent (_obter_headers é multithread).
        self._lock_ua = threading.Lock()

        # ---- Cache persistente de full-text (determinismo entre runs) ----
        # Reutiliza o texto/data/URL final já extraídos para a MESMA URL
        # original (ex.: janelas diárias repetidas). Protegido por lock porque
        # a análise full-text roda em PARALELO (ANALISE_WORKERS threads).
        self._sem_cache = sem_cache
        self._cache_fulltext = {}
        self._cache_novos = 0
        self._lock_cache = threading.Lock()
        if not sem_cache:
            self._carregar_cache_fulltext()

        # ---- Cooldown adaptativo do Google News (pós-429/503) ----
        # Começa no jitter aleatório padrão; dobra após cada 429/503 (até o
        # teto GN_JITTER_TETO) e cai lentamente em sucesso — menos 503 e menos
        # bloqueios por rajada.
        self._gn_espera_atual = random.uniform(
            config.GN_JITTER_MIN, config.GN_JITTER_MAX
        )

        # ---- Saúde dos feeds (registro por veículo) ----
        # _feed_erros: veículos cujos feeds diretos falharam neste run
        # (HTTP != 200, feed inválido/vazio, exceção). _saude_run: total de
        # notícias deduplicadas por veículo. Alimentam o histórico JSON
        # (saude.py) e os alertas de feed morto.
        self._feed_erros = set()
        self._lock_feed_erros = threading.Lock()
        self._saude_run = {}

    # ------------------------------------------------------------------
    # CABEÇALHOS HTTP (com rodízio de User-Agent)
    # ------------------------------------------------------------------
    def _carregar_cache_fulltext(self):
        """
        Carrega do disco o cache persistente de full-text (formato JSON).
        Estrutura: {"atualizado": ISO, "itens": {url: {"t": texto, "d": ISO
        ou null, "u": url_final}}}. Falha de leitura é não-fatal (cache
        recomeça vazio).
        """
        try:
            if os.path.isfile(config.ARQUIVO_CACHE_FULLTEXT):
                with open(config.ARQUIVO_CACHE_FULLTEXT, "r", encoding="utf-8") as fh:
                    dados = json.load(fh)
                itens = dados.get("itens", {}) if isinstance(dados, dict) else {}
                if isinstance(itens, dict):
                    self._cache_fulltext = itens
                    logger.info(
                        "Cache de full-text carregado: %d url(s) (atualizado em %s).",
                        len(itens),
                        dados.get("atualizado", "?"),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Não foi possível carregar o cache de full-text: %s (cache recomeça vazio).",
                exc,
            )
            self._cache_fulltext = {}

    def _salvar_cache(self):
        """
        Grava o cache de full-text em disco (gravação atômica: arquivo .tmp +
        os.replace). Chamado no fim da coleta e da análise; também a cada
        CACHE_FLUSH_A_CADA novas entradas. Falha de gravação é não-fatal.
        """
        try:
            if self._sem_cache:
                return
            os.makedirs(config.DIR_CACHE, exist_ok=True)
            with self._lock_cache:
                snapshot = dict(self._cache_fulltext)
            destino_tmp = config.ARQUIVO_CACHE_FULLTEXT + ".tmp"
            with open(destino_tmp, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "atualizado": config.agora_brasilia().isoformat(
                            timespec="seconds"
                        ),
                        "itens": snapshot,
                    },
                    fh,
                    ensure_ascii=False,
                )
            os.replace(destino_tmp, config.ARQUIVO_CACHE_FULLTEXT)
            logger.debug("Cache de full-text salvo (%d urls).", len(snapshot))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha ao salvar o cache de full-text: %s", exc)

    def _espera_gn(self):
        """
        Espera adaptativa do Google News (cooldown): dorme o valor atual do
        jitter (que sobe após 429/503 e desce em sucesso).
        """
        time.sleep(self._gn_espera_atual)

    def _obter_headers(self):
        """
        Retorna um dicionário de headers com um User-Agent do rodízio.
        A cada chamada, avança o índice para rodar entre os User-Agents
        reais configurados, reduzindo o risco de bloqueio por anti-bot.
        """
        user_agent = config.USER_AGENTS[self.user_agent_index % len(config.USER_AGENTS)]
        # Avança o índice para o próximo request. Protegido por lock: a análise
        # roda em MÚLTIPLAS threads (_obter_headers é chamado em paralelo).
        with self._lock_ua:
            self.user_agent_index += 1
        return {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }

    def _obter_headers_google(self):
        """
        Cabeçalhos para as requisições DIRECIONADAS ao Google News.
        Além do rodízio de User-Agent (herdado), varia o Accept-Language
        e o Accept a cada chamada para parecer tráfego diverso e reduzir
        a chance de bloqueio por rate-limit (HTTP 503).
        """
        headers = self._obter_headers()
        idiomas = [
            "pt-BR,pt;q=0.9,en;q=0.8",
            "pt-BR,pt;q=0.7,en-US,en;q=0.6",
            "en-US,en;q=0.9,pt-BR,pt;q=0.8",
            "pt-PT,pt;q=0.9,en-US,en;q=0.8",
            "pt-BR,pt;q=0.8,es;q=0.5,en;q=0.7",
        ]
        # user_agent_index já foi avançado em _obter_headers: usa-o como
        # semente fixa de variação do idioma pedido.
        headers["Accept-Language"] = idiomas[self.user_agent_index % len(idiomas)]
        headers["Accept"] = "application/atom+xml,application/rss+xml,application/xml;q=0.9,text/xml;q=0.8,*/*;q=0.7"
        headers["Referer"] = "https://news.google.com/"
        return headers

    # ------------------------------------------------------------------
    # LIMPEZA DE TÍTULOS (qualidade do relatório)
    # ------------------------------------------------------------------
    @staticmethod
    def _limpar_titulo(titulo, nome_veiculo=None, dominio=None):
        """
        Limpa o título da notícia para exibição no relatório:
          - Remove o sufixo que o Google News acrescenta ao título:
            "ARTIGO - Nome da Fonte" ou "ARTIGO - dominio.com.br".
          - Remove espaços extras.
        Retorna o título limpo.
        """
        titulo = (titulo or "").strip()
        if not titulo:
            return titulo

        sufixos = []
        if dominio:
            sufixos.append(re.escape(dominio))
            # O Google News pode exibir o domínio de origem com SUBdomínio
            # (ex.: "estadaori.estadao.com.br"); também remove esse formato.
            sufixos.append(r"(?:[\w-]+\.)*" + re.escape(dominio))
        if nome_veiculo:
            sufixos.append(re.escape(nome_veiculo))
            # Variações do nome: sem acento e/ou sem espaços (ex.: o Google
            # News pode anexar "Poder360" ao invés de "Poder 360").
            compacto = re.sub(r"\s+", "", nome_veiculo)
            if compacto != nome_veiculo:
                sufixos.append(re.escape(compacto))
        # Variação sem acento do nome do veículo (ex.: Estadao / Estadão).
        if nome_veiculo:
            from unicodedata import normalize

            sem_acento = "".join(
                c for c in normalize("NFD", nome_veiculo)
                if not __import__("unicodedata").combining(c)
            )
            if sem_acento != nome_veiculo:
                sufixos.append(re.escape(sem_acento))
                compacto_sem_acento = re.sub(r"\s+", "", sem_acento)
                sufixos.append(re.escape(compacto_sem_acento))

        for suf in sufixos:
            titulo = re.sub(
                rf"\s*-\s*{suf}\s*$", "", titulo, flags=re.IGNORECASE
            )
        # BR Investing: remove o subtítulo/tagline do portal que o Google News
        # anexa ao final (" - Investing.com Brasil - Finanças, Câmbio e
        # Investimentos"). Segue o mesmo padrão dos sufixos de veículo.
        if nome_veiculo and "Investing" in (nome_veiculo + (dominio or "")):
            titulo = re.sub(
                r"\s*[-|–]\s*Investing\.com\s*Brasil.*$",
                "",
                titulo,
                flags=re.IGNORECASE,
            )
        return titulo.strip()

    @staticmethod
    def _eh_titulo_lixo(titulo, nome_veiculo=None):
        """
        Detecta títulos que NAO são matérias (páginas de listagem/arquivo do
        WordPress indexadas pelo Google News). Esses itens poluem o relatório.
        Ex.: "Categoria: Mercado & Investimentos - Página 343 de 343".
        """
        t = (titulo or "").lower()
        # Páginas de listagem: "Página 343 de 343"
        if re.search(r"p[aá]gina\s+\d+\s+de\s+\d+", t):
            return True
        # Seções de arquivo/categoria (ex.: "Categoria: ...", "Arquivo de ...",
        # "Arquivo de Últimas Notícias", "Últimas Notícias" como página).
        if re.search(r"(categoria|arquivo|category|archive)\s*[:.›»\-]", t):
            return True
        if re.search(r"^(categoria|arquivo|category|archive)\s+(de|do|da|dos|das)\b", t):
            return True
        if t.startswith("últimas notícias") or t.startswith("ultimas noticias"):
            return True
        padrões_lixo = [
            "não encontrada",
            "nao encontrada",
            "página não existe",
            "sobre nós",
            "fale conosco",
            "mapa do site",
            "404",
            # BR Investing: páginas de cotações/ferramentas (não são notícias)
            "gráfico",
            "grafico |",
            "preço-alvo",
            "preco-alvo",
            "cotação hoje",
            "cotacao hoje",
            "fórum",
            "forum",
            "participações de",
            "participacoes de",
            "preço de",
            "preco de",
            "acusações de insider",
            # Conteúdo patrocinado/institucional (Blue Studio etc.)
            "agência de comunicação",
            "agencia de comunicacao",
        ]
        if any(p in t for p in padrões_lixo):
            return True
        # BR Investing: páginas de ativos no padrão "TICKER - Cotação Hoje" e
        # "Análise/Ações de <Ativo>" (tooling, não matéria).
        if nome_veiculo and "investing" in (nome_veiculo or "").lower():
            # Tooling do site (não são matérias).
            tooling = [
                "análise técnica",
                "analise tecnica",
                "análises das ações",
                "analises das acoes",
                "comprar ou vender",
                "histórico",
                "historico",
                "notícias (",
                "noticias (",
                "por que as ações da",
                "por que as acoes da",
                "estão subindo hoje",
                "estao subindo hoje",
                "fundo .*invest .*preço",
                "fundo .*invest .*preco",
                "fi em cotas de fundos",
            ]
            if any(p in t for p in tooling):
                return True
            # Linha de acionistas de fundos/empresas estrangeiras (página de
            # lista da bolsa NYSE, não matéria): "Acionistas Mulvihill Fund",
            # "Acionistas Jatt III Acquisition".
            if re.search(r"^acionistas\s+.*\s(fund|acquisition|utn)\s*$", t) or re.search(
                r"^acionistas\s+(jatt|rainier|nearthlab|mulvihill)\b", t
            ):
                return True
            if re.search(
                r"\b[a-z]{2,5}\d{1,2}\b.*(fórum|gráfico|análise|analise|cotação|cotacao|preço-alvo|preco-alvo)",
                t,
            ):
                return True
            # Página de cotação com ticker à esquerda: "AZEV4 - Azevedo e
            # Travassos PN", "ALO4 - Acelerar PN".
            if re.match(r"^[a-z]{3,5}\d(\d)?\s*-\s", t):
                return True
        return False

    # ------------------------------------------------------------------
    # DESDUPLICAÇÃO (RSS + Busca interna + Google News)
    # ------------------------------------------------------------------
    @staticmethod
    def _chave_dedupe(url):
        """
        Normaliza uma URL para servir de chave de desduplicação:
          - Remove espaço, padroniza minúsculas e remove '/' final.
          - Remove parâmetros de rastreamento comuns (utm_*, fbclid, gclid,
            ga_*, ref, oc etc.), que não alteram a matéria em si.

        Retorna a chave canônica (str) ou '' se a URL for vazia/inválida.
        """
        if not url:
            return ""
        base = url.strip().rstrip("/").lower()
        if "?" in base:
            parte_url, _, query = base.partition("?")
            parametros = [
                p for p in query.split("&")
                if p and not p.startswith(
                    ("utm_", "fbclid", "gclid", "ga_", "oc=", "ref=", "lipi=")
                )
            ]
            base = parte_url + ("?" + "&".join(parametros) if parametros else "")
        return base

    @staticmethod
    def _chave_titulo_dedupe(titulo):
        """
        Normaliza um título para desduplicação por título:
          - Minúsculas, sem pontuação, espaços colapsados.
        Captura a mesma matéria publicada com URLs diferentes (sindicalização
        ou GitHub de links de rastreamento).
        """
        if not titulo:
            return ""
        t = titulo.lower().strip()
        # Remove pontuação comum e colapsa espaços.
        t = re.sub(r"[\u2018\u2019'\"«»“”\u2013\u2014:;.,!?()\[\]/|]", " ", t)
        t = re.sub(r"\s+", " ", t)
        return t.strip()

    def _registrar_noticia(self, noticia):
        """
        Registra uma notícia na coleção DEDUPLICADA.
        Retorna True se foi adicionada (não era duplicada) ou False se já
        existia (mesma URL canônica ou mesmo título).

        Passa por um lock porque a coleta pode ser executada em paralelo
        (várias threads acessando os conjuntos ao mesmo tempo).
        """
        with self._lock_dedupe:
            chave_url = self._chave_dedupe(noticia.get("link"))
            if chave_url and chave_url in self._vistos_links:
                return False

            chave_titulo = self._chave_titulo_dedupe(noticia.get("titulo"))
            if chave_titulo and chave_titulo in self._vistos_titulos:
                return False

            if chave_url:
                self._vistos_links.add(chave_url)
            if chave_titulo:
                self._vistos_titulos.add(chave_titulo)
            return True

    # ------------------------------------------------------------------
    # PARSING DE DATAS
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_data_publicada(published_parsed):
        """
        Converte a struct_time de PUBLICAÇÃO ORIGINAL vinda do RSS ('published')
        em um objeto datetime. RECEBE EXCLUSIVAMENTE o campo 'published_parsed'.

        IMPORTANTE (regra de engenharia): 'updated_parsed' NÃO deve ser usado
        aqui, pois a janela temporal considera apenas a data de publicação
        original — jamais a data de atualização/modificação.

        Retorna datetime (naive, hora local) ou None se indisponível.
        """
        if not published_parsed:
            return None
        try:
            # published_parsed é uma struct_time (9 tuplas) SEMPRE normalizada
            # para UTC pelo feedparser. Convertemos para datetime e ajustamos
            # para o HORÁRIO DE BRASÍLIA (naive), para comparação segura e
            # consistente com a data_limite e com o relatório.
            dt = datetime.datetime(*published_parsed[:6], tzinfo=datetime.timezone.utc)
            return config.para_brasilia(dt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Não foi possível interpretar a data: %s", exc)
            return None

    @staticmethod
    def _parse_data_string(valor):
        """
        Converte uma string de data/hora (ex.: meta tags do HTML) em datetime.

        Suporta os formatos comuns do mercado:
            - ISO 8601 com/sem fuso: 2026-09-07T14:30:00-03:00, ...Z
            - Data apenas: 2026-09-07
            - Strings no padrão do Python: %Y-%m-%d %H:%M:%S

        Se a data vier com fuso horário, converte para hora local (naive)
        para comparação segura com os demais datetimes do sistema.

        Retorna datetime ou None (data inutilizável).
        """
        if not valor:
            return None
        valor = str(valor).strip()

        # REGRA DE TOLERÂNCIA DA JANELA TEMPORAL:
        # Se o portal fornecer APENAS a data (YYYY-MM-DD ou DD/MM/YYYY, com
        # ou sem sufixo de fuso), a publicação é assumida como o INÍCIO do dia
        # (00:00:00) no horário de Brasília — a interpretação mais tolerante
        # possível (a matéria nunca pode ser anterior ao início do próprio
        # dia). Isso evita descarte prematuro por margem de minutos lembrando
        # o caso em que o site publica às 00:30 e só informa o dia no HTML.
        for fmt_puro in ("%Y-%m-%d", "%d/%m/%Y"):
            candidato = valor[:-1] if valor.endswith(("Z", "z")) else valor
            try:
                return datetime.datetime.strptime(candidato, fmt_puro)
            except ValueError:
                continue

        # Remove o possível 'Z' final que indica UTC.
        if valor.endswith(("Z", "z")):
            valor = valor[:-1] + "+00:00"

        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d",
            # Formatos brasileiros (dia/mês/ano) — ex.: <time>06/09/2026 | 13h16</time>
            # comum em Estadão, Metrópoles e afins.
            "%d/%m/%Y | %Hh%M",
            "%d/%m/%Y \u2013 %Hh%M",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y",
        ):
            try:
                dt = datetime.datetime.strptime(valor, fmt)
                break
            except ValueError:
                continue
        else:
            # Último recurso: fromisoformat (Python 3.7+).
            try:
                dt = datetime.datetime.fromisoformat(valor)
            except ValueError:
                return None

        # Normaliza datetimes com fuso para o horário de Brasília (naive).
        if dt.tzinfo is not None:
            dt = config.para_brasilia(dt)
        return dt

    # ------------------------------------------------------------------
    # EXTRAÇÃO DA DATA DE PUBLICAÇÃO ORIGINAL PELO HTML
    # ------------------------------------------------------------------
    @staticmethod
    def _extrair_data_publicacao_do_html(soup):
        """
        Extrai a data de PUBLICAÇÃO ORIGINAL da página a partir das meta tags.

        Prioridade (regra de engenharia do filtro temporal):
            1. <meta property="article:published_time"> (ou name=)
            2. Schema.org datePublished (<meta property="datePublished"> ou
               <itemprop="datePublished">)
            3. <meta property="og:published_time">
            4. <time datetime="..."> como último recurso

        IGNORA deliberadamente (para nunca usar data de atualização):
            - article:modified_time
            - dateModified
            - updated_time

        Retorna datetime ou None.
        """
        candidatas = []

        # 1) JSON-LD (Schema.org embutido): <script type="application/ld+json">.
        #    Muito comum: @type NewsArticle com "datePublished" — coberto de
        #    forma genérica (varre chaves recursivamente, aceitando lists).
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                dado = json.loads(script.string or script.get_text() or "null")
            except (json.JSONDecodeError, TypeError):
                continue
            for valor in ScraperEngine._percorrer_ld(dado, "datePublished"):
                if valor:
                    candidatas.append(str(valor).strip())

        # 1b) article:published_time (mais comum no WordPress e sites de notícia).
        for attrs in ({"property": "article:published_time"}, {"name": "article:published_time"}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                candidatas.append(tag["content"].strip())

        # 2) Schema.org datePublished (Microdata via itemprop).
        tag = soup.find(attrs={"itemprop": "datePublished"})
        if tag:
            conteudo = tag.get("content") or tag.get("datetime")
            if conteudo:
                candidatas.append(conteudo.strip())

        # 2b) datePublished como property de meta tag.
        for attrs in ({"property": "datePublished"}, {"name": "datePublished"}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                candidatas.append(tag["content"].strip())

        # 3) og:published_time.
        for attrs in ({"property": "og:published_time"}, {"name": "og:published_time"}):
            tag = soup.find("meta", attrs=attrs)
            if tag and tag.get("content"):
                candidatas.append(tag["content"].strip())

        # 4) <time> como último recurso — usa o atributo 'datetime' OU o texto
        #    exibido (ex.: "06/09/2026 | 13h16", sem atributo no Estadão).
        if not candidatas:
            for tag in soup.find_all("time"):
                # Pula time tags explicitamente de modificação.
                if tag.get("itemprop", "") in ("dateModified", "updatedTime"):
                    continue
                if tag.get("datetime"):
                    candidatas.append(tag["datetime"].strip())
                elif tag.get_text(strip=True):
                    candidatas.append(tag.get_text(strip=True))

        for valor in candidatas:
            dt = ScraperEngine._parse_data_string(valor)
            if dt:
                return dt
        return None

    # ------------------------------------------------------------------
    # RESOLUÇÃO DA URL FINAL (após redirects)
    # ------------------------------------------------------------------
    @staticmethod
    def _eh_link_google_news(url):
        """
        Detecta links de rastreamento do Google News (news.google.com/rss/articles).
        Essas URLs são redirecionamentos por JavaScript: retornam uma página
        Angular de ~500KB sem o texto nem a URL real da matéria, o que torna
        qualquer tentativa de full-text/scraping inútil (e custosa).
        """
        return "news.google.com" in (url or "") and "/rss/articles/" in (url or "")

    def _resolver_url_google_news(self, url):
        """
        Resolve a URL de rastreamento do Google News (news.google.com/rss/articles/...)
        para a URL CANÔNICA do portal original, para que o link final do
        relatório não fique preso no domínio news.google.com.

        Estratégia (em ordem):
          1) googlenewsdecoder — biblioteca que decodifica o payload da URL
             (signature + timestamp) e recupera a URL real do artigo.
          2) Fallback manual (headers/cookies) — segue redirects HTTP e
             captura a URL canônica em Location (melhor esforço).
          3) Em caso de falha, retorna None — o chamador mantém o link
             original do Google News (funcional, sem regressão).

        O decoder interno faz requests SEM timeout explícito; envolvemos a
        chamada com socket.setdefaulttimeout para garantir que nenhuma
        resolução trave a esteira.

        PROTEÇÃO CONTRA RATE-LIMIT: a resolução também é uma requisição
        direcionada ao Google News — passa pelo mesmo lock serializado
        (_lock_gn_fluxo) e pelo jitter aleatório, para não estourar o limite
        de queries do Google quando os 6 workers de análise decodificam em
        paralelo.

        Retorna a URL canônica (str) ou None.
        """
        resultado = None

        with self._lock_gn_fluxo:
            with self._lock_gn:
                if self._gn_bloqueado:
                    return None

            self._espera_gn()

            # ---- Tentativa 1: googlenewsdecoder (decodificação do payload) ----
            # O endpoint batchexecute do Google sofre rate-limit intermitente sob
            # volume; um retry único com pequeno backoff eleva bastante a taxa de
            # sucesso sem custo significativo.
            timeout_anterior = socket.getdefaulttimeout()
            try:
                from googlenewsdecoder import gnewsdecoder

                for tentativa in (1, 2):
                    socket.setdefaulttimeout(config.TIMEOUT)
                    try:
                        resposta = gnewsdecoder(url)
                        if isinstance(resposta, dict) and resposta.get("status"):
                            canonica = (resposta.get("decoded_url") or "").strip()
                            if canonica and "news.google.com" not in canonica:
                                resultado = canonica
                                break
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "googlenewsdecoder (tentativa %d) falhou para %s...: %s",
                            tentativa, url[:70], exc,
                        )
                    finally:
                        socket.setdefaulttimeout(None)
                    if tentativa == 1:
                        time.sleep(1.2)  # Backoff curto antes do retry.
            except Exception as exc:  # noqa: BLE001
                logger.debug("googlenewsdecoder indisponível em %s...: %s", url[:70], exc)
            finally:
                socket.setdefaulttimeout(timeout_anterior)

            if not resultado:
                # ---- Tentativa 2: fallback manual (headers/cookies) ----
                try:
                    resposta_manual = requests.get(
                        url,
                        headers=self._obter_headers_google(),
                        timeout=config.TIMEOUT,
                        allow_redirects=False,
                        stream=True,
                    )
                    if resposta_manual.status_code in (301, 302, 303, 307, 308):
                        destino = urllib.parse.urljoin(
                            url, resposta_manual.headers.get("Location", "")
                        )
                        if "news.google.com" not in destino:
                            resultado = destino
                    resposta_manual.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Fallback manual de GN falhou para %s...: %s", url[:70], exc)

        if resultado:
            # Resolução OK: o Google está saudável — a espera adaptativa desce
            # (compartilha o mesmo _gn_espera_atual de _carregar_rss).
            with self._lock_gn:
                self._gn_espera_atual = max(
                    config.GN_JITTER_MIN,
                    self._gn_espera_atual * config.GN_JITTER_RECUPERACAO,
                )
            logger.debug("URL GN resolvida (decoder): %s", resultado[:90])
            logger.info("URL GN resolvida: %s", resultado[:90])
        return resultado

    def _resolver_url_final(self, url):
        """
        Segue os redirects (ex.: links de rastreamento do Google News) e
        retorna a URL final/real do artigo. Garante que o link que entra
        no relatório aponta para a matéria original, não para o redirecionador.

        Retorna a URL final; em caso de erro, retorna a própria URL original.
        """
        # Links do Google News não resolvem server-side (redirect por JS).
        if self._eh_link_google_news(url):
            return url
        try:
            response = requests.get(
                url,
                headers=self._obter_headers(),
                timeout=config.TIMEOUT,
                allow_redirects=True,
                stream=True,  # Não baixamos o corpo inteiro.
            )
            url_final = response.url or url
            response.close()
            return url_final
        except Exception as exc:  # noqa: BLE001
            logger.debug("Falha ao resolver URL final de %s: %s", url, exc)
            return url

    # ------------------------------------------------------------------
    # SANITIZAÇÃO DO HTML (antes do filtro semântico)
    # ------------------------------------------------------------------
    @staticmethod
    def _percorrer_ld(dado, chave):
        """
        Percorre uma estrutura JSON-LD (dicts e listas aninhadas) e devolve
        todos os valores encontrados para 'chave' (ex.: "datePublished").
        Generoso por design — ignora silenciosamente estruturas quebradas.
        """
        if isinstance(dado, dict):
            if chave in dado and dado[chave]:
                yield dado[chave]
            for valor in dado.values():
                yield from ScraperEngine._percorrer_ld(valor, chave)
        elif isinstance(dado, list):
            for item in dado:
                yield from ScraperEngine._percorrer_ld(item, chave)

    @staticmethod
    def _sanitizar_html(soup):
        """
        Remove os elementos de 'ruído' de uma página ANTES da extração do
        texto editorial puro (que alimenta o SemanticFilter):

          - Blocos estruturais de navegação/rodapé: <aside>, <footer>,
            <nav>, <header>.
          - Scripts/estilos/embeds: <script>, <style>, <noscript>, <iframe>.
          - Blocos com classe ou id 'suspeito' — conteúdo NÃO editorial que
            costuma citar temas do setor e polui a matriz de relevância:
            'newsletter', 'leia-tambem'/'leia também' (artigos relacionados),
            'publicidade', 'relacionad(a/os)', 'tags', 'assinatura'.

        É chamado apenas no fluxo de BeautifulSoup (o fallback padrão de
        full-text — o newspaper3k extrai texto sem essa granularidade).

        Retorna o próprio soup (modificado in-place) para encadeamento.
        """
        for etiqueta in ("aside", "footer", "nav", "header"):
            for no in soup.find_all(etiqueta):
                no.decompose()

        for no in soup(
            ["script", "style", "noscript", "iframe", "form", "button"]
        ):
            no.decompose()

        padrao_ruido = re.compile(
            r"newsletter|leia[-_]?tambem|leia[-_]?tamb[eé]m|"
            r"publicidade|relacionad|tags|assinatura|coment[áa]rios",
            re.IGNORECASE,
        )
        for atributo in ("class", "id"):
            for no in soup.find_all(attrs={atributo: padrao_ruido}):
                no.decompose()

        return soup

    # ------------------------------------------------------------------
    # PLANO B — SCRAPLING (bypass de anti-bot/403/layout mudado)
    # ------------------------------------------------------------------
    @staticmethod
    def _parece_bloqueio(status, html_text):
        """
        Detecta resposta bloqueada/desafio de anti-bot. O requests pode voltar
        HTTP 200 com uma página-desafio (iframe 'cf-chl', captcha, "just a
        moment"...). Nesses casos o Scrapling entra como plano B.
        """
        if status in config.SCRAPLING_FALLBACK_ALVO_STATUS:
            return True
        amostra = (html_text or "")[:4000].lower()
        return any(
            marcador in amostra
            for marcador in (
                "captcha",
                "cf-challenge",
                "cf-chl-",
                "checking your browser",
                "just a moment",
                "attention required",
            )
        )

    def _buscar_html_scrapling(self, url):
        """
        PLANO B: baixa a URL via Scrapling (Fetcher), que impersona o TLS e os
        headers de um navegador real — contorna proteções básicas de anti-bot
        (Cloudflare interstitial, checagens por User-Agent padrão, etc.).

        Ordem (do mais barato ao mais pesado):
          1) Fetcher (HTTP/TLS impersonado, SEM navegador) — resolve a maioria
             dos bloqueios;
          2) StealthyFetcher (Chromium headless) — SÓ quando config.
             SCRAPLING_STEALTH estiver True E o Fetcher voltar sem <p> (página
             renderizada por JS) ou falhar.

        Import é PREGUIÇOSO e falhas são não-fatais: se a biblioteca não estiver
        instalada (`pip install "scrapling[fetchers]"`) ou a requisição falhar,
        retorna None e o pipeline segue exatamente como antes (sem regressão).

        Retorna o HTML (str) ou None.
        """
        try:
            from scrapling.fetchers import Fetcher
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Scrapling não disponível (instale 'scrapling[fetchers]'): %s",
                exc,
            )
            return None
        StealthyFetcher = None
        if config.SCRAPLING_STEALTH:
            try:
                from scrapling.fetchers import StealthyFetcher
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "StealthyFetcher não disponível (requer playwright): %s",
                    exc,
                )

        html_fetcher = None
        tempo_anterior = socket.getdefaulttimeout()
        try:
            # 1) Fetcher (sem navegador): passa barato, resolve a maioria.
            try:
                page = Fetcher.get(
                    url,
                    impersonate="chrome",
                    stealthy_headers=True,
                    timeout=config.TIMEOUT,
                )
                if 200 <= page.status < 400:
                    html_txt = page.body.decode(
                        page.encoding or "utf-8", errors="replace"
                    )
                    # Conteúdo já veio (tem <p>) OU o browser está desligado:
                    # não vale a pena gastar navegador.
                    if not StealthyFetcher or self._tem_paragrafos(html_txt):
                        return html_txt
                    # Página que parece renderizar por JS: guarda o que veio e
                    # tenta o browser abaixo.
                    html_fetcher = html_txt
                else:
                    logger.debug(
                        "Scrapling retornou HTTP %s para %s", page.status, url
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Fetcher falhou para %s: %s", url, exc)

            # 2) StealthyFetcher (browser): último recurso, só se habilitado e
            # o Fetcher não trouxe o corpo (JS/desafio duro).
            if StealthyFetcher is not None:
                try:
                    socket.setdefaulttimeout(config.TIMEOUT * 3)
                    page = StealthyFetcher.fetch(url, headless=True)
                    if 200 <= page.status < 400:
                        return page.body.decode(
                            page.encoding or "utf-8", errors="replace"
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("StealthyFetcher falhou para %s: %s", url, exc)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Fallback Scrapling falhou para %s: %s", url, exc)
        finally:
            socket.setdefaulttimeout(tempo_anterior)
        return html_fetcher

    @staticmethod
    def _tem_paragrafos(html_text):
        """
        True se o HTML já contém ao menos um <p> com texto útil — sinal de que
        a página NÃO depende de JavaScript para exibir o corpo editorial (e o
        Fetcher simples resolve, sem precisar de navegador).
        """
        try:
            soup = BeautifulSoup(html_text or "", "lxml")
            return any(p.get_text(strip=True) for p in soup.find_all("p"))
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _extrair_corpo_paragrafos(html_text):
        """
        Sanitiza o HTML (removendo ruído) e extrai o texto editorial dos <p>.
        Reutilizado pelo full-text (requests e fallback Scrapling) para que o
        plano B produza EXATAMENTE o mesmo formato de saída — a validação
        semântica e a regra de publicação ficam intactas.
        """
        try:
            soup = BeautifulSoup(html_text, "lxml")
            ScraperEngine._sanitizar_html(soup)
            return "\n".join(
                p.get_text(strip=True)
                for p in soup.find_all("p")
                if p.get_text(strip=True)
            ).strip()
        except Exception:  # noqa: BLE001
            return ""

    def _baixar_feed_com_fallback(self, url_feed, nome_veiculo):
        """
        Baixa o corpo de um feed RSS com timeout garantido + User-Agent real.
        Se o servidor bloquear (HTTP != 200, com destaque para 403/429/5xx) e
        o plano B Scrapling estiver ligado, tenta obter o mesmo conteúdo com
        impersonação de TLS/headers (bypass de anti-bot básico).

        Retorna o conteúdo do feed (bytes/str) ou None em caso de falha.
        """
        try:
            resposta = requests.get(
                url_feed,
                headers=self._obter_headers(),
                timeout=config.TIMEOUT,
            )
            if resposta.status_code == 200:
                return resposta.content
            logger.warning(
                "Feed %s retornou HTTP %s (%s)",
                url_feed,
                resposta.status_code,
                nome_veiculo,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Falha no download do feed %s (%s): %s",
                nome_veiculo,
                url_feed,
                exc,
            )

        if config.SCRAPLING_FALLBACK:
            html_scrapling = self._buscar_html_scrapling(url_feed)
            if html_scrapling:
                logger.info(
                    "Fallback Scrapling OK no feed de %s (%s)",
                    nome_veiculo,
                    url_feed,
                )
                return html_scrapling
        return None

    # ------------------------------------------------------------------
    # EXTRAÇÃO DO TEXTO COMPLETO + DATA (Full-Text + metadados)
    # ------------------------------------------------------------------
    def _obter_texto_e_data(self, url):
        """
        Busca o corpo completo da matéria (full-text) E a data de publicação
        original (via meta tags do HTML).

        Estratégia (Capítulo 2.2):
            Primeiro resolve a URL final (chance de ser redirect do Google
            News). Depois tenta o newspaper3k; se falhar, cai no fallback
            com BeautifulSoup extraindo as tags <p>.

        IMPORTANTE: a citação do cliente pode estar no 4º parágrafo da
        notícia, então NÃO basta ler o título/description do RSS.

        CACHE: se a MESMA URL original já foi analisada em run anterior (ou
        ainda neste run), devolve o texto/data/URL final do cache persistente
        — sem NENHUMA requisição de rede (determinismo total entre runs).

        Retorna a tupla:
            (texto_completo: str, data_pub_original: datetime|None,
             url_final: str)
        Sempre retorna uma tupla — nunca quebra o fluxo.
        """
        # ---- 0) CACHE: URL original já resolvida em run anterior? ----
        if not self._sem_cache:
            with self._lock_cache:
                entrada = self._cache_fulltext.get(url)
            if entrada is not None:
                texto_cache = str(entrada.get("t", ""))
                data_pub_cache = None
                if entrada.get("d"):
                    data_pub_cache = self._parse_data_string(entrada["d"])
                url_final_cache = str(entrada.get("u", url))
                logger.debug("Cache full-text (hit): %s...", url[:70])
                return (texto_cache, data_pub_cache, url_final_cache)

        # ---- 0.5) URLs do Google News (redirect por JS sem conteúdo estático) ----
        # ANTES de pular, tentamos resolver a URL CANÔNICA do portal original
        # (googlenewsdecoder). Se a resolução tiver sucesso, o fluxo de
        # full-text + data continua NORMALMENTE sobre o artigo real — texto
        # completo (matriz semântica completa), data original em meta tags e
        # link do próprio site no relatório (não preso no news.google.com).
        # Sem sucesso, mantemos o link do Google News e avaliamos pelo
        # título+resumo (o máximo possível para o veículo).
        if self._eh_link_google_news(url):
            url_canonica = self._resolver_url_google_news(url)
            if url_canonica:
                logger.debug(
                    "GN resolvido (%s...) — full-text sobre o artigo real.",
                    url_canonica[:70],
                )
                url = url_canonica
            else:
                logger.debug(
                    "GN sem resolução — avaliando por título+resumo: %s...",
                    url[:70],
                )
                return ("", None, url)

        # ---- 1) Resolve a URL final (segue redirects) ----
        url_final = self._resolver_url_final(url)

        texto = ""
        html_text = ""

        # ---- TENTATIVA 1: newspaper3k ----
        try:
            import newspaper

            artigo = newspaper.Article(url_final, timeout=config.TIMEOUT)
            artigo.download()
            artigo.parse()
            texto = (artigo.text or "").strip()
            # Guarda o HTML bruto baixado para extrair a data by meta tags.
            html_text = artigo.html or ""
            if not texto:
                html_text = ""
        except Exception as exc:  # noqa: BLE001
            logger.debug("newspaper3k falhou para %s: %s", url_final, exc)

        # ---- TENTATIVA 2: fallback com BeautifulSoup ----
        if not texto:
            obtido_ok = False
            bloqueado = False
            scrapling_tentado = False
            try:
                response = requests.get(
                    url_final,
                    headers=self._obter_headers(),
                    timeout=config.TIMEOUT,
                )
                response.raise_for_status()
                # Força o encoding para UTF-8 quando possível (cuidando de acentos).
                if response.encoding is None or response.encoding.lower() not in ("utf-8", "utf8"):
                    response.encoding = response.apparent_encoding or "utf-8"
                html_text = response.text
                obtido_ok = True
                bloqueado = self._parece_bloqueio(
                    response.status_code, html_text
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Scraping HTML falhou para %s: %s", url_final, exc)

            # ---- TENTATIVA 3: Scrapling (plano B) quando o requests falhou ----
            # Dispara em: exceção de rede, HTTP de bloqueio (403/429/5xx) ou
            # página-desafio de anti-bot escondida atrás de um 200.
            if config.SCRAPLING_FALLBACK and (not obtido_ok or bloqueado):
                scrapling_tentado = True
                html_scrapling = self._buscar_html_scrapling(url_final)
                if html_scrapling:
                    logger.info(
                        "Fallback Scrapling OK (anti-bot) para %s...",
                        url_final[:80],
                    )
                    html_text = html_scrapling

            if html_text:
                texto = self._extrair_corpo_paragrafos(html_text)

            # ---- TENTATIVA 4: seletor de <p> vazio (layout mudou) ----
            # requests respondeu 200 com um HTML "normal", mas nenhum <p> foi
            # achado; o Scrapling pode entregar o corpo com outra visão. Só
            # entra se o plano B ainda não foi tentado neste loop para a URL.
            if not texto and not scrapling_tentado and config.SCRAPLING_FALLBACK:
                html_scrapling = self._buscar_html_scrapling(url_final)
                if html_scrapling and not (html_text and html_scrapling == html_text):
                    logger.info(
                        "Fallback Scrapling OK (conteúdo vazio) para %s...",
                        url_final[:80],
                    )
                    html_text = html_scrapling
                    texto = self._extrair_corpo_paragrafos(html_text)

        # ---- DATA DE PUBLICAÇÃO ORIGINAL (via meta tags do HTML) ----
        data_pub_original = None
        if html_text:
            try:
                soup = BeautifulSoup(html_text, "lxml")
                data_pub_original = self._extrair_data_publicacao_do_html(soup)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Falha ao extrair data do HTML de %s: %s", url_final, exc)

        # ---- Grava no cache (chave = URL ORIGINAL, antes da resolução) ----
        # Só nos fluxos de sucesso completo (não cacheia a URL GN não resolvida
        # — isso travaria a resolução para sempre se o Google estiver fora).
        if not self._sem_cache:
            flushar = False
            with self._lock_cache:
                self._cache_fulltext[url] = {
                    "t": texto.strip(),
                    "d": (
                        data_pub_original.isoformat(timespec="seconds")
                        if data_pub_original
                        else None
                    ),
                    "u": url_final,
                }
                self._cache_novos += 1
                # Limite de tamanho: remove a entrada mais antiga (a dict
                # preserva a ordem de inserção).
                while len(self._cache_fulltext) > config.CACHE_MAX_ENTRADAS:
                    del self._cache_fulltext[next(iter(self._cache_fulltext))]
                if self._cache_novos >= config.CACHE_FLUSH_A_CADA:
                    self._cache_novos = 0
                    flushar = True
            if flushar:
                self._salvar_cache()

        return (texto.strip(), data_pub_original, url_final)

    # ------------------------------------------------------------------
    # COLETA DE UM ÚNICO VEÍCULO VIA RSS DIRETO
    # ------------------------------------------------------------------
    def _coletar_feed(self, nome_veiculo, rss_urls):
        """
        Coleta e processa as notícias de UM veículo a partir de um ou mais
        feeds RSS (rss_urls é uma lista; todos são mesclados).

        FILTRO TEMPORAL (regra crítica de engenharia):
            - A janela de tempo considera SOMENTE a data de PUBLICAÇÃO ORIGINAL
              ('published' / 'published_parsed'). A data de ATUALIZAÇÃO
              ('updated' / 'updated_parsed') é IGNORADA.
            - Entrada com 'published_parsed' DENTRO da janela → aceita.
            - Entrada com 'published_parsed' ANTERIOR à data_limite → descartada
              (pode ter sido listada por ter sido apenas atualizada).
            - Entrada SEM 'published_parsed' (só 'updated') NÃO é descartada
              aqui de forma agressiva: ela fica com data_publicacao=None e a
              validação definitiva é adiada para o pipeline, que extrai o
              'article:published_time' do HTML — a fonte da PUBLICAÇÃO ORIGINAL.
              Se nem no HTML houver data, a matéria é descartada (não pode ser
              validada contra a janela).

        Retorna: lista de dicts de notícias do veículo. Feed com erro retorna
                 lista vazia (sem interromper o loop).
        """
        if isinstance(rss_urls, str):
            rss_urls = [rss_urls]

        noticias = []
        for rss_url in rss_urls:
            noticias.extend(self._coletar_feed_unico(nome_veiculo, rss_url))
        return noticias

    def _coletar_feed_unico(self, nome_veiculo, rss_url):
        """Coleta e processa as notícias de UM feed RSS específico."""
        noticias = []

        def _marcar_falha():
            with self._lock_feed_erros:
                self._feed_erros.add(nome_veiculo)

        try:
            logger.info("Coletando RSS de: %s (%s)", nome_veiculo, rss_url)
            # Baixa o feed via requests com timeout garantido + User-Agent
            # real. feedparser.parse(url) direto usa urllib interno SEM timeout,
            # o que pode prender um worker (e atrasar todo o run) num feed lento.
            # Em bloqueio (403/429/5xx) o plano B Scrapling assume a baixa.
            conteudo_feed = self._baixar_feed_com_fallback(rss_url, nome_veiculo)
            if conteudo_feed is None:
                _marcar_falha()
                return noticias
            feed = feedparser.parse(conteudo_feed)

            # Verifica se houve erro no parse do feed.
            if getattr(feed, "bozo", False) and not feed.entries:
                _marcar_falha()
                logger.warning(
                    "Feed inválido ou vazio para %s (%s): %s",
                    nome_veiculo,
                    rss_url,
                    getattr(feed, "bozo_exception", "erro desconhecido"),
                )
                return noticias

            for entry in feed.entries:
                titulo = entry.get("title", "").strip()
                titulo = self._limpar_titulo(titulo, nome_veiculo=nome_veiculo)
                if self._eh_titulo_lixo(titulo, nome_veiculo=nome_veiculo):
                    continue  # Página de listagem/arquivo, não é matéria.
                # Extrai o link (pode estar em entry.link ou entry.guid).
                link = entry.get("link") or entry.get("guid") or ""
                link = link.strip()

                # Resumo/description vindo do RSS (palito preliminar).
                resumo = (entry.get("summary") or entry.get("description") or "").strip()

                # Data de PUBLICAÇÃO ORIGINAL — APENAS published_parsed.
                # NUNCA usar updated_parsed para julgar a janela temporal.
                data_pub = self._parse_data_publicada(
                    entry.get("published_parsed")
                )

                # --- Regra temporal (publicação original) ---
                if data_pub is not None and data_pub < self.data_limite:
                    # Publicada ANTES da janela (mesmo que atualizada depois)
                    # → descarta imediatamente.
                    continue
                if (
                    data_pub is not None
                    and self.data_limite_max is not None
                    and data_pub > self.data_limite_max
                ):
                    # Modo calendário: publicada DEPOIS do fim do intervalo
                    # (ex.: "04/09 a 06/09" com matéria do dia 07) → descarta.
                    continue

                # Sem published_parsed: NÃO usa updated_parsed. Deixa
                # data_publicacao=None e o pipeline decidirá com base no
                # 'article:published_time' do HTML (publicação original).
                # isso preserva feeds que só trazem 'updated' sem violar a regra.

                if not titulo or not link:
                    continue  # Matéria incompleta, pula.

                noticias.append(
                    {
                        "veiculo": nome_veiculo,
                        "titulo": titulo,
                        "link": link,
                        "resumo": resumo,
                        "data_publicacao": data_pub,  # None → validar no HTML.
                        "full_text": None,   # Preenchido sob demanda.
                        "is_relevante": None,
                        "clientes_citados": [],
                    }
                )
        except Exception as exc:  # noqa: BLE001
            _marcar_falha()
            logger.error(
                "ERRO ao coletar feed de %s (%s): %s",
                nome_veiculo,
                rss_url,
                exc,
            )
        return noticias

    # ------------------------------------------------------------------
    # GOOGLE NEWS RSS (helpers + fallback + BUSCA DIRECIONADA por termo)
    # ------------------------------------------------------------------
    def _sufixo_when(self):
        """
        Converte o número de horas para o formato 'when:' do Google News.
        Ex.: 24h -> when:24h ; 48h -> when:2d ; 30h -> when:30h ; 72h -> when:3d.

        LIMITE SUPERIOR (7 dias): o Google News aceita no máximo 'when:7d'.
        Para janelas maiores, usa-se 7d — o filtro ESTRITO de data continua
        aplicado no sistema (publicação original dentro da janela real), ou
        seja, um resultado extra capturado apenas é descartado depois.
        """
        horas = max(1, min(self.horas_passadas, 168))

        if horas == 24:
            return "24h"
        if horas % 24 == 0:
            return f"{horas // 24}d"
        return f"{horas}h"

    def _carregar_rss(self, url):
        """
        Baixa e faz o parse de um feed RSS com timeout garantido, User-Agent
        real e RETRY curto em respostas de limitação (429/503) — o Google News
        aplica throttle intermitente por IP; um retry com backoff recupera boa
        parte das consultas sem custo significativo.

        Circuit-breaker: se o Google News responder 429/503 de forma contínua
        (config.GN_MAX_FALHAS_SEGUIDAS), as camadas Google News são desativadas
        no restante do run — o pipeline continua com RSS direto + Lupa.

        PROTEÇÃO CONTRA RATE-LIMIT: todas as requisições AO Google News são
        SERIALIZADAS pelo lock _lock_gn_fluxo (worker único) e precedidas de um
        jitter aleatório time.sleep(random.uniform(0.8, 1.8)) — enquanto os
        feeds RSS diretos e as páginas dos portais seguem em PARALELO.
        Os cabeçalhos GN são rotacionados (_obter_headers_google) para parecer
        tráfego diverso e reduzir o risco de 503 por rajada de queries.
        """
        with self._lock_gn_fluxo:
            with self._lock_gn:
                if self._gn_bloqueado:
                    return None

            # Jitter dedicado às consultas Google News (rate-limit).
            self._espera_gn()

            for tentativa in (1, 2):
                try:
                    resposta = requests.get(
                        url,
                        headers=self._obter_headers_google(),
                        timeout=config.TIMEOUT,
                    )
                    if resposta.status_code in (429, 503):
                        # Cooldown adaptativo: dobra a espera (sem passar do
                        # teto), protegendo de novos 503/block por rajada.
                        with self._lock_gn:
                            self._gn_espera_atual = min(
                                self._gn_espera_atual * config.GN_JITTER_FATOR,
                                config.GN_JITTER_TETO,
                            )
                        if tentativa == 1:
                            time.sleep(2.0)
                            continue
                        with self._lock_gn:
                            self._gn_falhas_seguidas += 1
                            if self._gn_falhas_seguidas >= config.GN_MAX_FALHAS_SEGUIDAS:
                                self._gn_bloqueado = True
                                logger.warning(
                                    "Google News respondendo 429/503 de forma contínua — "
                                    "camadas GN desativadas neste run (RSS + Lupa continuam)."
                                )
                        return None
                    with self._lock_gn:
                        self._gn_falhas_seguidas = 0
                        self._gn_bloqueado = False
                        # Sucesso: a espera "desce" lentamente (nunca abaixo
                        # do jitter mínimo).
                        self._gn_espera_atual = max(
                            config.GN_JITTER_MIN,
                            self._gn_espera_atual * config.GN_JITTER_RECUPERACAO,
                        )
                    if resposta.status_code != 200:
                        return None
                    return feedparser.parse(resposta.content)
                except requests.RequestException as exc:
                    if tentativa == 1:
                        time.sleep(1.0)
                        continue
                    logger.debug("Falha ao carregar RSS %s: %s", url[:60], exc)
                    return None
        return None

    def _parse_google_news_feed(self, nome_veiculo, feed, dominio=None, origem="google-news"):
        """
        Converte as entradas de um feed RSS do Google News na estrutura padrão
        de notícia do sistema, aplicando:
          - Limpeza de título (remove o sufixo ' - <fonte>' acrescentado).
          - Descarte de títulos-lixo (páginas de listagem/indexação).
          - Filtro temporal ESTRITO: somente 'published_parsed' (publicação
            original) decide; sem data ou fora da janela → descarta.
          - Origem rotulada ('google-news' fallback ou 'busca-google').

        O link de rastreamento é mantido de forma preguiçosa (lazy) — será
        validado/reutilizado no pipeline, evitando requisições extras para
        entradas irrelevantes.

        Retorna: lista de dicts de notícias (mesma estrutura do feed direto).
        """
        noticias = []
        for entry in (feed.entries if feed else []):
            titulo = entry.get("title", "").strip()
            titulo = self._limpar_titulo(
                titulo, nome_veiculo=nome_veiculo, dominio=dominio
            )
            if self._eh_titulo_lixo(titulo, nome_veiculo=nome_veiculo):
                continue  # Não é matéria (página de listagem etc.).
            link = entry.get("link") or entry.get("guid") or ""
            link = link.strip()
            resumo = (entry.get("summary") or "").strip()
            data_pub = self._parse_data_publicada(
                entry.get("published_parsed")
            )

            # Mesma regra temporal: só o published_parsed vale.
            if data_pub is None:
                continue
            if data_pub < self.data_limite:
                continue
            if self.data_limite_max is not None and data_pub > self.data_limite_max:
                continue

            if not titulo or not link:
                continue

            noticias.append(
                {
                    "veiculo": nome_veiculo,
                    "titulo": titulo,
                    "link": link,  # redirect do Google News (resolvido depois).
                    "resumo": resumo,
                    "data_publicacao": data_pub,
                    "full_text": None,
                    "is_relevante": None,
                    "clientes_citados": [],
                    "origem": origem,
                }
            )
        return noticias

    def _coletar_via_google_news(self, nome_veiculo, dominio):
        """
        Fallback robusto quando o feed direto do veículo falha ou está vazio.

        Usa o RSS de busca do Google News:
            https://news.google.com/rss/search?q=site:<dominio> when:Nh

        Isso contorna feeds mortos, panoramas de paywall e mudanças de URL.

        A data considerada pela janela temporal é a 'published_parsed'
        (publicação original), seguindo a mesma regra crítica de engenharia.

        Retorna: lista de dicts de notícias (mesma estrutura do feed direto).
        """
        try:
            sufixo_tempo = self._sufixo_when()
            query = f"site:{dominio} when:{sufixo_tempo}"
            url_google = config.GOOGLE_NEWS_RSS_BASE.format(
                query=urllib.parse.quote(query)
            )

            logger.info(
                "Fallback Google News para %s (query: %s)", nome_veiculo, query
            )
            feed = self._carregar_rss(url_google)
            return self._parse_google_news_feed(nome_veiculo, feed, dominio=dominio)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ERRO no fallback Google News de %s: %s", nome_veiculo, exc
            )
        return []

    def _coletar_via_google_news_termo(self, nome_veiculo, dominio):
        """
        BUSCA DIRECIONADA via Google News — consultas focadas por TERMO.

        Para os portais de ECONOMIA GERAL (Folha, Estadão, Valor, Metrópoles,
        UOL, etc.) que NÃO possuem busca interna server-side consultável, usa a
        sintaxe de busca avançada do Google News dentro do domínio monitorado:

            site:<dominio> "<TERMO>" when:<Nh>

        para cada termo crítico:
          a) As entidades-alvo (ABRASCA, Cátilo Cândido) e reguladores
             (CVM, Otto Lobo, B3).
          b) Termos regulatórios de alta relevância (IPO, Oferta Pública,
             Governance, Tokenização, OPA, Follow-on).

        Isso captura matérias sobre os clientes/regulação que NÃO chegam à
        home page nem ao feed principal — complementando a varredura de capas.

        Filtros aplicados aqui (e reforçados no pipeline):
          - Filtro temporal estrito (somente data de publicação original).
          - Desduplicação pela chave única (URL canônica / título) na
            consolidação final em _coletar_veiculo.

        Retorna: lista de dicts de notícias (mesma estrutura do feed direto).
        """
        coletadas = []
        sufixo_tempo = self._sufixo_when()
        for termo in config.BUSCA_TERMOS:
            try:
                query = f'site:{dominio} "{termo}" when:{sufixo_tempo}'
                url_google = config.GOOGLE_NEWS_RSS_BASE.format(
                    query=urllib.parse.quote(query)
                )
                logger.debug(
                    "Busca direcionada %s — consulta: %s", nome_veiculo, query
                )
                feed = self._carregar_rss(url_google)
                registros = self._parse_google_news_feed(
                    nome_veiculo, feed, dominio=dominio, origem="busca-google"
                )
                coletadas.extend(registros[: config.BUSCA_MAX_POR_TERMO])
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Falha na busca direcionada de '%s' em %s: %s",
                    termo,
                    nome_veiculo,
                    exc,
                )
        return coletadas

    # ------------------------------------------------------------------
    # BUSCA INTERNA DO VEÍCULO ("LUPA") — TARGETED SEARCH
    # ------------------------------------------------------------------
    def _busca_feed_wp(self, nome_veiculo, url_feed_busca):
        """
        Consulta o FEED RSS dos resultados de busca interna de um portal
        WordPress (ex.: https://site/?s=termo&feed=rss). Esse feed entrega
        resultados com DATA DE PUBLICAÇÃO ORIGINAL ('published_parsed') e
        LINKS DO PRÓPRIO SITE (a URL real, sem redirects do Google News).

        Aplica estritamente o filtro temporal: só 'published_parsed' decide;
        entradas sem data ou fora da janela são descartadas.

        Retorna lista de dicts de notícias (mesma estrutura do feed direto).
        """
        registros = []
        try:
            # Baixa o feed via requests (timeout garantido + User-Agent real)
            # e faz o parse do conteúdo — feedparser.parse(url) direto não
            # expõe timeout, arriscando travar o pipeline num feed lento. Se o
            # portal bloquear (403/429/5xx), o plano B Scrapling tenta baixar.
            conteudo_feed = self._baixar_feed_com_fallback(
                url_feed_busca, nome_veiculo
            )
            if conteudo_feed is None:
                return registros
            feed = feedparser.parse(conteudo_feed)

            if getattr(feed, "bozo", False) and not feed.entries:
                return registros

            for entry in feed.entries:
                titulo = (entry.get("title") or "").strip()
                titulo = self._limpar_titulo(
                    titulo, nome_veiculo=nome_veiculo
                )
                if self._eh_titulo_lixo(titulo, nome_veiculo=nome_veiculo):
                    continue
                link = (entry.get("link") or entry.get("guid") or "").strip()
                resumo = (entry.get("summary") or entry.get("description") or "").strip()
                data_pub = self._parse_data_publicada(
                    entry.get("published_parsed")
                )

                # Filtro temporal estrito: publicado fora da janela → descarta.
                if data_pub is not None and data_pub < self.data_limite:
                    continue
                if (
                    data_pub is not None
                    and self.data_limite_max is not None
                    and data_pub > self.data_limite_max
                ):
                    continue

                if not titulo or not link:
                    continue

                registros.append(
                    {
                        "veiculo": nome_veiculo,
                        "titulo": titulo,
                        "link": link,
                        "resumo": resumo,
                        "data_publicacao": data_pub,
                        "full_text": None,
                        "is_relevante": None,
                        "clientes_citados": [],
                        "origem": "busca-interna",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Falha no feed de busca de %s: %s", nome_veiculo, exc)
        return registros

    def _busca_html(self, nome_veiculo, url_busca_html):
        """
        Fallback da busca interna via página HTML de resultados
        (ex.: https://site/?s=termo sem o sufixo de feed).

        Extrai os links de matéria dos blocos <article> (padrão dos temas
        WordPress). NÃO há data de publicação no HTML da listagem, então as
        entradas ficam com data_publicacao=None e a validação temporal final
        acontece no pipeline, lendo o 'article:published_time' do artigo.

        Retorna lista de dicts de notícias (mesma estrutura).
        """
        registros = []
        try:
            resposta = requests.get(
                url_busca_html,
                headers=self._obter_headers(),
                timeout=config.TIMEOUT,
            )
            resposta.raise_for_status()
            soup = BeautifulSoup(resposta.text, "lxml")

            # Blocos de matéria: <article> (título dentro de <h2> ou <h3>).
            artigos_vistos = {}
            for artigo in soup.find_all("article"):
                h_titulo = artigo.find(["h1", "h2", "h3"])
                if not h_titulo:
                    continue
                link_tag = h_titulo.find("a")
                if not link_tag or not (link_tag.get("href") or "").strip():
                    continue
                titulo = h_titulo.get_text(strip=True)
                if not titulo or self._eh_titulo_lixo(
                    titulo, nome_veiculo=nome_veiculo
                ):
                    continue
                href = link_tag["href"].strip()
                if href.startswith("/"):
                    href = urllib.parse.urljoin(url_busca_html, href)
                # Evita links repetidos na mesma página de resultados.
                artigos_vistos.setdefault(href, titulo)

            for href, titulo in artigos_vistos.items():
                titulo = self._limpar_titulo(titulo)
                registros.append(
                    {
                        "veiculo": nome_veiculo,
                        "titulo": titulo,
                        "link": href,
                        "resumo": "",
                        "data_publicacao": None,  # Validação no pipeline (HTML).
                        "full_text": None,
                        "is_relevante": None,
                        "clientes_citados": [],
                        "origem": "busca-interna",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Falha na busca HTML de %s: %s", nome_veiculo, exc)
        return registros

    def _coletar_via_busca(self, nome_veiculo, info_busca):
        """
        Varredura por BUSCA INTERNA ("Lupa") — estratégia híbrida de busca:

        Para cada termo (7 entidades + termos regulatórios críticos), consulta
        o endpoint de busca do veículo, ordena por "mais recentes" e aplica o
        filtro estrito de data de publicação original. Os links capturados são
        do PRÓPRIO SITE (não do Google News).

        Fluxo por termo:
          1. Se o portal suporta feed de resultados (tipo "wp") → usa
             '?s=<termo>&feed=rss' (RSS com data — ideal).
          2. Se o feed vier vazio/falhar → cai na página HTML de resultados
             (quando habilitado) e extrai os links dos <article>.
          3. Ordena os resultados por data (mais recentes primeiro) e limita
             ao teto configurado (BUSCA_MAX_POR_TERMO).

        Retorna: lista de dicts de notícias (mesma estrutura do feed direto).
        """
        url_template = info_busca.get("url", "")
        tipo = info_busca.get("tipo", "wp")
        html_fallback = info_busca.get("html_fallback", True)

        if not url_template or "{termo}" not in url_template:
            return []

        foram_coletadas = []
        for termo in config.BUSCA_TERMOS:
            url_termo = url_template.format(
                termo=urllib.parse.quote_plus(termo)
            )
            try:
                registros = []
                # 1) Feed de resultados (WordPress): melhor fonte de datas.
                if tipo == "wp":
                    registros = self._busca_feed_wp(nome_veiculo, url_termo)

                # 2) Fallback para a página HTML de resultados.
                if not registros and html_fallback:
                    url_html = url_termo.replace("&feed=rss", "").replace(
                        "&feed=rss2", ""
                    )
                    registros = self._busca_html(nome_veiculo, url_html)

                # 3) Ordena por mais recentes e limita o volume por termo.
                registros.sort(
                    key=lambda n: n.get("data_publicacao")
                    or datetime.datetime.min,
                    reverse=True,
                )
                foram_coletadas.extend(
                    registros[: config.BUSCA_MAX_POR_TERMO]
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "ERRO na busca de '%s' em %s: %s",
                    termo,
                    nome_veiculo,
                    exc,
                )

        return foram_coletadas

    # ------------------------------------------------------------------
    # COLETA DE UM VEÍCULO (RSS + Busca interna + Busca direcionada + fallback)
    # ------------------------------------------------------------------
    def _coletar_veiculo(self, nome_veiculo, info_veiculo):
        """
        Coleta um veículo com ESTRATÉGIA HÍBRIDA em quatro camadas:

            1. VARREdura RSS ("Broad Crawl"): feed direto/últimas notícias —
               captura a pauta geral na janela de tempo.
            2. BUSCA INTERNA DO PORTAL ("Lupa"/Targeted Search): para os
               portais com busca server-side (WordPress em BUSCA_SITES),
               consulta o endpoint de busca pelas 7 entidades + termos
               regulatórios, com links do PRÓPRIO SITE (não do Google News).
            3. BUSCA DIRECIONADA VIA GOOGLE NEWS (Targeted Search): para os
               portais de ECONOMIA GERAL sem busca interna consultável
               (Folha, Estadão, Valor, Metrópoles, UOL etc.) — consultas
               focadas site:<dominio> "<TERMO>" when:<Nh> capturam matérias
               sobre clientes/regulação que não chegam à capa nem ao feed.
            4. FALLBACK Google News (domínio completo): último recurso quando
               RSS e busca não trouxerem nada (link de rastreamento só quando
               não há alternativa).

        DESDUPLICAÇÃO: matérias capturadas por mais de uma via (capa + busca)
        têm uma ÚNICA entrada no relatório (chave única: URL canônica e/ou
        título normalizado).

        Retorna: lista de dicts de notícias do veículo.
        """
        # ---- Camada 1: RSS direto (Broad Crawl) ----
        noticias = self._coletar_feed(nome_veiculo, info_veiculo["rss"])
        n_rss = len(noticias)

        # ---- Camadas 2 e 3: Busca interna / Busca direcionada ----
        dominio = info_veiculo.get("dominio")
        info_busca = config.BUSCA_SITES.get(nome_veiculo)
        if info_busca and dominio:
            # Portal com busca interna server-side (WordPress): links do site.
            logger.info(
                "Busca interna (Lupa) para %s (%d termos)...",
                nome_veiculo,
                len(config.BUSCA_TERMOS),
            )
            noticias.extend(self._coletar_via_busca(nome_veiculo, info_busca))
        elif dominio:
            if n_rss >= config.GN_SKIP_TERMO_ATE_ITENS:
                # RSS direto já rendeu na janela: a busca focada GN quase só
                # reproduziria o mesmo conteúdo — pulando (menos carga no
                # Google News, item 3). O fallback site:<domínio> (Camada 4,
                # 1 única consulta) continua disponível se mesmo assim o
                # veículo vier vazio.
                logger.info(
                    "RSS direto de %s rendeu %d na janela — pulando busca "
                    "direcionada GN por termo (menos carga no Google News).",
                    nome_veiculo,
                    n_rss,
                )
            else:
                # Portal de economia geral SEM busca interna consultável e com
                # feed raso: consultas focadas via Google News
                # (site:dominio "TERMO" when:Nh).
                logger.info(
                    "Busca direcionada (Google News por termo) para %s (%d termos)...",
                    nome_veiculo,
                    len(config.BUSCA_TERMOS),
                )
                noticias.extend(
                    self._coletar_via_google_news_termo(nome_veiculo, dominio)
                )

        # ---- Camada 4: fallback Google News (domínio completo, último recurso) ----
        if not noticias and dominio:
            noticias = self._coletar_via_google_news(nome_veiculo, dominio)

        # ---- Desduplicação (intra e inter-veículo) ----
        unicas = []
        for noticia in noticias:
            if self._registrar_noticia(noticia):
                unicas.append(noticia)

        # Saúde: total deduplicado deste veículo (histórico em saude.py).
        self._saude_run[nome_veiculo] = len(unicas)

        return unicas

    # ------------------------------------------------------------------
    # MÉTODO PRINCIPAL DE COLETA (TODOS OS VEÍCULOS)
    # ------------------------------------------------------------------
    def coletar_todos(self):
        """
        Percorre os 18 veículos e coleta todas as notícias dentro da janela
        de tempo (considerando exclusivamente a data de publicação original).

        DESEMPENHO / RESILIÊNCIA (Capítulo 7):
          - A coleta é 100% I/O de rede, então os veículos são consultados EM
            PARALELO (ThreadPoolExecutor, config.COLETA_WORKERS): um portal
            lento não segura a esteira enquanto houver workers livres.
          - Todo request mantém timeout de segurança (config.TIMEOUT); um
            portal fora do ar ocupa, no máximo, um worker por alguns segundos.
          - A desduplicação é protegida por lock (thread-safe), garantindo a
            unicidade mesmo com múltiplas threads registrando notícias ao
            mesmo tempo.
          - Cada veículo roda com try/except próprio: um falha e os demais
            seguem normalmente.

        Retorna: lista única (achatada) de dicionários de notícias.
        """
        todas_noticias = []
        total_veiculos = len(config.VEICULOS)

        logger.info("─" * 70)
        logger.info(
            "Iniciando coleta em PARALELO de %d veículos (workers: %d)...",
            total_veiculos,
            config.COLETA_WORKERS,
        )

        itens = [
            (indice, nome, info)
            for indice, (nome, info) in enumerate(
                config.VEICULOS.items(), start=1
            )
        ]

        def coletar_com_log(item):
            """Coleta UM veículo dentro de um worker (nunca lança)."""
            indice, nome, info = item
            logger.info("[%d/%d] Coletando: %s", indice, total_veiculos, nome)
            try:
                return nome, self._coletar_veiculo(nome, info)
            except Exception as exc:  # noqa: BLE001
                logger.error("ERRO ao coletar veículo %s: %s", nome, exc)
                return nome, []

        try:
            with ThreadPoolExecutor(
                max_workers=config.COLETA_WORKERS
            ) as executor:
                futuras = {
                    executor.submit(coletar_com_log, item): item
                    for item in itens
                }
                for futura in as_completed(futuras):
                    nome, noticias_ou = futura.result()
                    todas_noticias.extend(noticias_ou)
                    logger.info(
                        "    → %d notícia(s) de %s (%s)",
                        len(noticias_ou),
                        nome,
                        futuras[futura][0],
                    )
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha na execução paralela da coleta: %s", exc)
            for _, nome, info in itens:
                try:
                    todas_noticias.extend(self._coletar_veiculo(nome, info))
                except Exception as sub_exc:  # noqa: BLE001
                    logger.error(
                        "ERRO ao coletar %s (fallback serial): %s",
                        nome,
                        sub_exc,
                    )

        logger.info("─" * 70)
        logger.info(
            "TOTAL BRUTO de notícias coletadas: %d (janela: %s horas)",
            len(todas_noticias),
            self.horas_passadas,
        )
        # Persistência do cache de full-text (novas urls desta coleta).
        self._salvar_cache()
        return todas_noticias