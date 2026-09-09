# =============================================================================
# link_shortener.py
# -----------------
# Módulo LinkShortener: encurtamento de URLs com failover rígido (redundância)
# e validação dupla, garantindo que o relatório JAMAIS receba um link quebrado.
#
# Lógica exata (conforme especificação do módulo):
#   1) Preparo: urllib.parse.quote(url, safe=":/%?&=#") + User-Agent real.
#   2) Tentativa principal (IS.GD):
#        GET https://is.gd/create.php?format=json&url=<CODIFICADA>  (timeout=5)
#        Se status 200 → lê o JSON e extrai a chave "shorturl".
#   3) Failover (TinyURL):
#        GET https://tinyurl.com/api-create.php?url=<CODIFICADA>    (timeout=5)
#        Resposta em texto puro → usa response.text.strip().
#   4) Validação dupla (obrigatória):
#        requests.head(link_curto, timeout=5, allow_redirects=True).
#        Status HTTP < 400 (ex.: 200, 301, 302) → link válido, retorna.
#   5) Fallback final:
#        Se TODAS as APIs falharem ou a validação detectar link quebrado
#        (ex.: 404), retorna a URL ORIGINAL (longa). Nunca levanta exceção;
#        sempre preserva a execução silenciosamente.
# =============================================================================

import logging
import urllib.parse
import requests

import config

logger = logging.getLogger(__name__)


class LinkShortener:
    """
    Encurta URLs com IS.GD (tentativa principal) e TinyURL (failover),
    aplicando validação dupla obrigatória e retornando a URL original se
    nenhum dos encurtadores produzir um link válido.
    """

    def __init__(self):
        """Prepara um User-Agent real para as requisições (evita bloqueios)."""
        self.headers = {"User-Agent": config.USER_AGENTS[0]}

    # ------------------------------------------------------------------
    # PASSO 1: PREPARO DA URL
    # ------------------------------------------------------------------
    @staticmethod
    def _codificar_url(url):
        """
        Codifica a URL preservando os caracteres estruturais de uma URL
        (scheme, path, params, query) conforme a especificação:
            safe=":/%?&=#"
        Retorna a string codificada pronta para uso na query da API.
        """
        return urllib.parse.quote(url, safe=":/%?&=#")

    # ------------------------------------------------------------------
    # PASSO 2: TENTATIVA PRINCIPAL — IS.GD (formato JSON)
    # ------------------------------------------------------------------
    def _tentar_isgd(self, url_codificada):
        """
        Chama https://is.gd/create.php?format=json&url=<CODIFICADA> com
        timeout=5. Se o status for 200, lê o JSON e extrai a chave "shorturl".

        Retorna o link curto do IS.GD ou None em qualquer falha (status != 200,
        timeout, JSON inválido, sem chave 'shorturl', resposta de erro da API).
        """
        try:
            url_api = (
                f"{config.ISGD_API_URL}?format=json&url={url_codificada}"
            )
            resposta = requests.get(
                url_api,
                headers=self.headers,
                timeout=config.ISGD_TIMEOUT,
            )
            if resposta.status_code != 200:
                logger.debug("IS.GD retornou status %s.", resposta.status_code)
                return None

            dados = resposta.json()
            link_curto = (dados.get("shorturl") or "").strip()
            if not link_curto:
                logger.debug("IS.GD não retornou a chave 'shorturl'.")
                return None
            return link_curto
        except Exception as exc:  # noqa: BLE001  (timeout, rede, JSON inválido)
            logger.debug("IS.GD falhou: %s", exc)
            return None

    # ------------------------------------------------------------------
    # PASSO 3: FAILOVER — TinyURL (texto puro)
    # ------------------------------------------------------------------
    def _tentar_tinyurl(self, url_codificada):
        """
        Chamada de failover automático:
            GET https://tinyurl.com/api-create.php?url=<CODIFICADA> (timeout=5)
        O TinyURL responde em texto puro: response.text.strip().

        Retorna o link curto do TinyURL ou None em qualquer falha (status != 200,
        timeout, resposta de erro em texto — nunca começa com http).
        """
        try:
            url_api = (
                f"{config.TINYURL_API_URL}?url={url_codificada}"
            )
            resposta = requests.get(
                url_api,
                headers=self.headers,
                timeout=config.TINYURL_TIMEOUT,
            )
            if resposta.status_code != 200:
                logger.debug("TinyURL retornou status %s.", resposta.status_code)
                return None

            link_curto = resposta.text.strip()
            # Respostas de erro do TinyURL vem como texto ("Error: ...").
            if not link_curto.lower().startswith("http"):
                logger.debug("TinyURL retornou resposta inválida: %r", link_curto[:60])
                return None
            return link_curto
        except Exception as exc:  # noqa: BLE001
            logger.debug("TinyURL falhou: %s", exc)
            return None

    # ------------------------------------------------------------------
    # PASSO 4: VALIDAÇÃO DUPLA (obrigatória)
    # ------------------------------------------------------------------
    def _validar_link(self, link_curto):
        """
        Dispara requests.head(link_curto, timeout=5, allow_redirects=True).
        Se o status HTTP final (após redirects) for MEHOR que 400 — ex.: 200,
        301 ou 302 — o link é considerado VÁLIDO e retorna True.

        Qualquer erro de rede, timeout ou status >= 400 → False (link inválido).
        """
        try:
            resposta = requests.head(
                link_curto,
                headers=self.headers,
                timeout=config.VALIDATION_TIMEOUT,
                allow_redirects=True,
            )
            return resposta.status_code < config.STATUS_VALIDO_MAX
        except Exception as exc:  # noqa: BLE001
            logger.debug("Validação dupla falhou para %s: %s", link_curto, exc)
            return False

    # ------------------------------------------------------------------
    # MÉTODO PRINCIPAL COM FAILOVER RÍGIDO
    # ------------------------------------------------------------------
    def encurtar(self, url_original):
        """
        Encurta uma URL com redundância total. Fluxo exato:

            1. Codifica a URL (safe=":/%?&=#").
            2. Tenta o IS.GD (JSON, chave 'shorturl').
            3. Se o IS.GD falhar, dispara o TinyURL (texto puro).
            4. Valida o link curto obtido (HEAD; status deve ser < 400).
            5. Se tudo falhar, retorna a URL original longa.

        GARANTIA: o método nunca levanta exceção e nunca devolve um link
        quebrado — no pior caso, preserva a URL original.
        """
        url_original = (url_original or "").strip()
        if not url_original:
            return url_original

        url_codificada = self._codificar_url(url_original)

        # Ordem rígida de providers: IS.GD primeiro, TinyURL como failover.
        for tentativa in (self._tentar_isgd, self._tentar_tinyurl):
            link_curto = tentativa(url_codificada)
            if link_curto and self._validar_link(link_curto):
                logger.debug("Link curto aprovado (%s): %s",
                             tentativa.__name__, link_curto)
                return link_curto

        # Fallback final: mantém a URL original. Silencioso e seguro.
        logger.info(
            "Encurtamento indisponível (IS.GD e TinyURL) — preservando URL original."
        )
        return url_original