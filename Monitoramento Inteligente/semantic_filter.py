# =============================================================================
# semantic_filter.py
# ------------------
# Filtro semântico GENÉRICO do módulo "Monitoramento Inteligente".
#
# Diferente dos módulos dedicados (Energia/ABRASCA), aqui NÃO há regras de
# negócio fixas de um setor. Tudo vem da demanda (via config):
#
#   Nível 1 — Citação direta: o cliente (e variações/representantes) citado
#             no texto aprova a matéria instantaneamente.
#   Nível 2 — Tema por palavras-chave: a matéria só é aprovada se REALMENTE
#             trata do tema, e não apenas catar a palavra. Regras:
#               (a) chave FORTE presente (demanda marca quais são) → aprova;
#               (b) 2+ palavras-chave distintas no texto → aprova;
#               (c) 1 palavra-chave + termo de CONTEXTO POSITIVO → aprova;
#               (d) palavra-chave no TÍTULO/resumo (sinal editorial) → aprova.
#             Caso contrário, uma única keyword solta (ex.: "comércio" num
#             texto sobre comércio de drogas) NÃO aprova.
#   Nível 4 — Exclusão/falso tema: config.BLACKLIST (global + termos de
#             exclusão da demanda) tem OVERRIDE: vetando, mata a matéria.
#
# Casos de exemplo (varejo):
#   "Comércio de drogas desarticulado no RJ"        -> keyword "comércio" (1),
#                                                      sem contexto, sem título
#                                                      → REPROVADO.
#   "Varejo físico acelera vendas no Natal"         -> "varejo"+"vendas" (2),
#                                                      contexto "varejo" → APROVADO.
#   "Amazon amplia marketplace no Brasil"           -> "Amazon"+"marketplace",
#                                                      chave forte → APROVADO.
# =============================================================================

import logging
import re

import config

logger = logging.getLogger(__name__)


class SemanticFilter:
    """Aplica a matriz genérica (Níveis 1, 2 e 4) sobre o texto de uma notícia."""

    # ------------------------------------------------------------------
    # UTILITÁRIOS DE TEXTO
    # ------------------------------------------------------------------
    @staticmethod
    def _normalizar(texto):
        """Minúsculas + sem acentos (busca case/acento-insensitive)."""
        from unicodedata import normalize

        texto = texto or ""
        texto = texto.lower()
        texto = normalize("NFD", texto)
        texto = "".join(
            c for c in texto if not __import__("unicodedata").combining(c)
        )
        return texto

    @staticmethod
    def _contem(texto_normalizado, termo):
        """Substrição simples (para termos com espaço ou <=4 letras usa
        word boundary — compatível com o comportamento dos módulos antigos)."""
        if " " not in termo and len(termo) <= 4:
            return (
                re.search(
                    rf"(?<![a-z0-9]){re.escape(termo)}(?![a-z0-9])",
                    texto_normalizado,
                )
                is not None
            )
        return termo in texto_normalizado

    @staticmethod
    def _contem_termo(texto_normalizado, termo):
        """
        Match RIGOROSO para palavras-chave/cliente: termo de uma palavra
        exige word boundary (evita "Amazon" casando com "amazônia"); termos
        compostos (com espaço) usam substring.
        """
        termo = SemanticFilter._normalizar(termo)
        if not termo:
            return False
        if " " in termo:
            return termo in texto_normalizado
        return (
            re.search(
                rf"(?<![a-z0-9]){re.escape(termo)}(?![a-z0-9])",
                texto_normalizado,
            )
            is not None
        )

    @staticmethod
    def _contem_permissivo(texto_normalizado, termo):
        """
        Match PERMISSIVO para termos de CONTEXTO (confirmadores): substring
        simples. Ex.: contexto "loja" confirma "lojas", "lojinha", etc.
        Só é usado junto de avaliação de contexto, onde há uma palavra-chave
        exigida em coocorrência — o que delimita o falso positivo.
        """
        termo = SemanticFilter._normalizar(termo)
        if not termo:
            return False
        return termo in texto_normalizado

    # ------------------------------------------------------------------
    # NÍVEL 1 — CITAÇÃO DIRETA DO CLIENTE
    # ------------------------------------------------------------------
    def _nivel1_clientes(self, texto_normalizado):
        citados = []
        for cliente, variacoes in config.CLIENTES.items():
            for variacao in variacoes:
                if self._contem_termo(texto_normalizado, variacao):
                    if cliente not in citados:
                        citados.append(cliente)
                    break
        return citados

    # ------------------------------------------------------------------
    # NÍVEL 2 — TEMA POR PALAVRAS-CHAVE COM VALIDAÇÃO DE CONTEXTO
    # ------------------------------------------------------------------
    def _nivel2_tema(self, texto_normalizado, titulo_normalizado=""):
        keywords_presentes = [
            k for k in config.PALAVRAS_CHAVE
            if self._contem_termo(texto_normalizado, k)
        ]
        keywords_no_titulo = [
            k for k in config.PALAVRAS_CHAVE
            if titulo_normalizado
            and self._contem_termo(titulo_normalizado, k)
        ]

        # Chave forte no texto → tema confirmado (aprova sozinha).
        for forte in config.CHAVES_CHAVE_FORTES:
            if self._contem_termo(texto_normalizado, forte):
                logger.debug("Nível 2 aprovado pela chave FORTE: '%s'", forte)
                return True

        # Sem nenhuma keyword, a matéria não pode ser do tema → reprova.
        if not keywords_presentes and not keywords_no_titulo:
            return False

        # 2+ keywords distintas no texto → tema confirmado.
        if len(keywords_presentes) >= 2:
            logger.debug(
                "Nível 2 aprovado por %d palavras-chave distintas.",
                len(keywords_presentes),
            )
            return True

        # Keyword no TÍTULO é sinal editorial forte de que o tema domina.
        if keywords_no_titulo:
            logger.debug(
                "Nível 2 aprovado: keyword '%s' no título.",
                keywords_no_titulo[0],
            )
            return True

        # 1 keyword + termo de CONTEXTO POSITIVO → tema confirmado.
        # (Contexto usa match PERMISSIVO: "loja" confirma "lojas".)
        for termo in config.TERMOS_CONTEXTO:
            if self._contem_permissivo(texto_normalizado, termo):
                logger.debug(
                    "Nível 2 aprovado: keyword '%s' + contexto '%s'.",
                    keywords_presentes[0],
                    termo,
                )
                return True

        logger.debug(
            "Nível 2 REJEITADO: keyword '%s' solta, sem contexto/título.",
            keywords_presentes[0] or "sem keyword",
        )
        return False

    # ------------------------------------------------------------------
    # PRÉ-FILTRO (main.py) — sinal permissivo de candidatura
    # ------------------------------------------------------------------
    def _pre_tem_sinal(self, texto_normalizado):
        """Versão SUPERCONJUNTA usada só no pré-filtro: qualquer cliente,
        keyword, chave forte ou termo de contexto já manda ao full-text."""
        if config.CLIENTES and self._nivel1_clientes(texto_normalizado):
            return True
        for termo in config.PALAVRAS_CHAVE:
            if self._contem_termo(texto_normalizado, termo):
                return True
        for termo in config.CHAVES_CHAVE_FORTES:
            if self._contem_termo(texto_normalizado, termo):
                return True
        for termo in config.TERMOS_CONTEXTO:
            if self._contem_permissivo(texto_normalizado, termo):
                return True
        return False

    # ------------------------------------------------------------------
    # NÍVEL 4 — EXCLUSÃO / FALSO TEMA (OVERRIDE)
    # ------------------------------------------------------------------
    def _nivel4_blacklist(self, texto_normalizado):
        for palavra in config.BLACKLIST:
            if self._contem(texto_normalizado, self._normalizar(palavra)):
                logger.info("Exclusão acionada por: '%s'", palavra)
                return True
        return False

    # ------------------------------------------------------------------
    # AVALIAÇÃO DA MATÉRIA
    # ------------------------------------------------------------------
    def avaliar(self, texto, titulo_resumo=""):
        """
        Aplica Níveis 4 → 1 → 2. Retorna (is_relevante, clientes_citados).
        """
        texto_normalizado = self._normalizar(texto)
        titulo_normalizado = self._normalizar(titulo_resumo)

        # ---- Nível 4 primeiro (override total) ----
        if self._nivel4_blacklist(texto_normalizado):
            return (False, [])

        # ---- Nível 1: cliente citado ----
        clientes = self._nivel1_clientes(texto_normalizado)
        if clientes:
            return (True, clientes)

        # ---- Nível 2: tema por keywords com validação de contexto ----
        if self._nivel2_tema(texto_normalizado, titulo_normalizado):
            return (True, [])

        return (False, [])