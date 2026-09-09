# =============================================================================
# semantic_filter.py
# ------------------
# Módulo SemanticFilter: o CÉREBRO do sistema (projeto ABRASCA).
#
# Implementa a matriz de busca semântica e NLP com 4 níveis de
# validação lógica:
#
#   Nível 1: Citação Direta (Alvos Primários — ABRASCA + reguladores)
#   Nível 2: Cenário Macro e Regulatório (Mercado de Capitais)
#   Nível 3: Rede de Arrasto com Dupla Validação Contextual
#   Nível 4: Filtro Negativo (Blacklist de Ambiguidade) — OVERRIDE total
#
# A classe recebe o full-text de uma matéria e devolve:
#   is_relevante   -> bool (matéria passa ou não)
#   clientes_citados -> lista de clientes encontrados (Nível 1)
#
# A blacklist REMOVE a matéria da fila de forma incondicional, mesmo que
# uma citação direta (Nível 1) tenha sido encontrada.
# =============================================================================

import logging
import re

import config

logger = logging.getLogger(__name__)


class SemanticFilter:
    """
    Aplica a matriz de filtragem semântica sobre o texto de uma notícia.
    """

    # ------------------------------------------------------------------
    # CONSTRUTOR
    # ------------------------------------------------------------------
    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # UTILITÁRIOS DE TEXTO
    # ------------------------------------------------------------------
    @staticmethod
    def _normalizar(texto):
        """
        Normaliza o texto para busca case-insensitive segura:
          - converte para minúsculas
          - remove acentos (para capturar variações)
        """
        from unicodedata import normalize

        texto = texto or ""
        texto = texto.lower()

        texto = normalize("NFD", texto)
        texto = "".join(c for c in texto if not __import__("unicodedata").combining(c))
        return texto

    @staticmethod
    def _contem(texto_normalizado, termo):
        """
        Verifica se 'termo' está presente no texto (já normalizado).
        Usa busca por palavra inteira (word boundary) para siglas curtas.
        """
        if " " not in termo and len(termo) <= 4:
            return re.search(rf"(?<![a-z0-9]){re.escape(termo)}(?![a-z0-9])", texto_normalizado) is not None
        return termo in texto_normalizado

    # ------------------------------------------------------------------
    # NÍVEL 1: CITAÇÃO DIRETA (Clientes)
    # ------------------------------------------------------------------
    def _nivel1_clientes(self, texto_normalizado):
        """
        Procura os nomes exatos das entidades-alvo no texto.
        Cada cliente possui variações (config.CLIENTES).
        Retorna: lista dos clientes citados.
        """
        citados = []
        for cliente, variacoes in config.CLIENTES.items():
            for variacao in variacoes:
                if self._contem(texto_normalizado, self._normalizar(variacao)):
                    if cliente not in citados:
                        citados.append(cliente)
                    break
        return citados

    # ------------------------------------------------------------------
    # NÍVEL 2: CENÁRIO MACRO E REGULATÓRIO
    # ------------------------------------------------------------------
    def _tem_ancora_capital(self, texto_normalizado):
        """
        Âncora inequívoca de mercado de capitais no texto
        (config.TERMOS_COOCORRENCIA_CAPITAIS).
        """
        return self._tem_coocorrencia_capitais(texto_normalizado)

    def _n2_qualquer_chave(self, texto_normalizado):
        """
        Versão PERMISSIVA usada SÓ pelo pré-filtro (main.py): retorna True se
        QUALQUER chave de Nível 2 (forte, macro ou estrita) aparecer no texto,
        INDEPENDENTE de âncora.

        O pré-filtro precisa ser um SUPERCONJUNTO do filtro completo: a chave
        macro pode estar só no título/resumo, mas a ÂNCORA só no full-text — o
        pré-filtro jamais pode descartar nesse caso; a decisão estrita fica
        para a avaliação completa.
        """
        for chave in config.CHAVES_NIVEL2:
            if self._contem(texto_normalizado, self._normalizar(chave)):
                return True
        return False

    def _nivel2_macro_regulatorio(self, texto_normalizado, titulo_normalizado=""):
        """
        Procura as chaves compostas do monitoramento institucional
        (CVM, B3, tokenização, governança, IPO, reguladores...).

        VALIDAÇÃO EM DOIS NÍVEIS (anti-ruído):
          - CHAVES_NIVEL2_FORTES (CVM, B3, IPO, governança...): qualquer uma
            delas no texto APROVA sozinha — são inequívocas de mercado.
          - CHAVES_NIVEL2_MACRO (Selic, PIB, inflação, fiscal, orçamento,
            câmbio, crédito, Compliance/Transparência...): aprovam APENAS se
            também existir uma ÂNCORA de mercado de capitais no texto OU no
            título — senão, um artigo político que cita "orçamento" uma vez
            poluiria o clipping.
          - CHAVES_NIVEL2_ESTRITAS (escala 6x1, jornada, Pix, reforma
            trabalhista...): NUNCA aprovam sozinhas — exigem a âncora de
            mercado de capitais no texto.

        Retorna True se a(validação correta da chave) passar.
        """
        # ---- 1º grupo: chaves FORTES (aprovam sozinhas) ----
        for chave in config.CHAVES_NIVEL2_FORTES:
            if self._contem(texto_normalizado, self._normalizar(chave)):
                logger.debug("Nível 2 (forte) acionado pela chave: '%s'", chave)
                return True

        # ---- 2º grupo: chaves MACRO (precisam de âncora) ----
        # Critérios (qualquer um aprova):
        #   (a) a chave macro está no TÍTULO/RESUMO — sinal editorial de que a
        #       matéria É sobre o tema macro (ex.: "Banco Central mantém Selic");
        #   (b) há âncora de mercado de capitais no texto OU no título — matéria
        #       macro TOCADA ao mercado (ex.: "Selic pesa em Bolsa").
        # Um artigo político/STF que cita "orçamento" uma vez no corpo não
        # passa (nem título macro, nem âncora).
        def _chave_no_titulo(chave):
            return bool(
                titulo_normalizado
                and self._contem(titulo_normalizado, self._normalizar(chave))
            )

        tem_ancora_no_texto = self._tem_ancora_capital(texto_normalizado)
        tem_ancora_no_titulo = bool(
            titulo_normalizado and self._tem_ancora_capital(titulo_normalizado)
        )
        for chave in config.CHAVES_NIVEL2_MACRO:
            if not self._contem(texto_normalizado, self._normalizar(chave)):
                continue
            if _chave_no_titulo(chave) or tem_ancora_no_texto or tem_ancora_no_titulo:
                logger.debug(
                    "Nível 2 (macro) acionado pela chave: '%s' "
                    "(título ou âncora).",
                    chave,
                )
                return True
            logger.debug(
                "Nível 2 (macro) REJEITADO para chave '%s' (só no corpo, sem "
                "âncora de mercado de capitais).",
                chave,
            )

        # ---- 3º grupo: chaves ESTRITAS (nunca aprovam sozinhas) ----
        for chave in config.CHAVES_NIVEL2_ESTRITAS:
            if self._contem(texto_normalizado, self._normalizar(chave)):
                if tem_ancora_no_texto:
                    logger.debug(
                        "Nível 2 (estrita) acionado pela chave: '%s' (com âncora).",
                        chave,
                    )
                    return True
                logger.debug(
                    "Nível 2 (estrita) REJEITADO para chave '%s' (sem âncora).",
                    chave,
                )

        return False

    # ------------------------------------------------------------------
    # GUARDAS DE COOCORRÊNCIA (Nível 3)
    # ------------------------------------------------------------------
    def _tem_coocorrencia_capitais(self, texto_normalizado):
        """
        Verifica se há coocorrência com ao menos um termo inequívoco do
        mercado de capitais (config.TERMOS_COOCORRENCIA_CAPITAIS).
        Sem isso, uma aprovação apoiada apenas em arrastos genéricos +
        jargão genérico NÃO pode passar.
        """
        for termo in config.TERMOS_COOCORRENCIA_CAPITAIS:
            if self._contem(texto_normalizado, self._normalizar(termo)):
                return True
        return False

    def _tem_ancora_brasil(self, texto_normalizado):
        """
        Verifica se o texto cita o MERCADO BRASILEIRO (config.
        TERMOS_ANCORA_BRASIL): empresa/companhia brasileira, B3/Ibovespa,
        CVM, real, "mercado brasileiro" etc. Usado como porta de entrada
        para veículos de fora (ex.: BR Investing), que trazem muito
        noticiário de empresas estrangeiras.

        Retorna True se QUALQUER termo de âncora Brasil aparecer.
        """
        for termo in config.TERMOS_ANCORA_BRASIL:
            if self._contem(texto_normalizado, self._normalizar(termo)):
                return True
        return False

    def _tem_origem_estrangeira(self, texto_normalizado):
        """
        Detecta no título/resumo indicadores de que a matéria trata de uma
        companhia MERCADO ESTRANGEIRO (config.INDICADORES_ORIGEM_ESTRANGEIRA
        e config.COMPANHIAS_ESTRANGEIRAS_IGNORAR): Nasdaq/NYSE, país
        estrangeiro, agência reguladora dos EUA (SEC), e companhias
        estrangeiras conhecidas. Usado na porta de saída global: matéria sem
        âncora Brasil nesta superfície é reprovada.
        """
        for termo in config.INDICADORES_ORIGEM_ESTRANGEIRA:
            if self._contem(texto_normalizado, self._normalizar(termo)):
                return True
        for nome in config.COMPANHIAS_ESTRANGEIRAS_IGNORAR:
            if self._contem(texto_normalizado, self._normalizar(nome)):
                return True
        return False

    @staticmethod
    def _eh_arrasto_generico(palavra_normalizada):
        """
        Arrastos genéricos: "mercado", "ações", "empresa", "companhia"
        — comuns demais para, sozinhos, garantir contexto de mercado
        de capitais.
        """
        return any(
            palavra_normalizada == SemanticFilter._normalizar(g)
            for g in config.GENERIC_ARRASTO
        )

    @staticmethod
    def _eh_jargao_generico(jargao_normalizado):
        """
        Jargões de negócios FRACOS/genéricos — não garantem contexto de
        mercado de capitais (mercado, empresa, companhia, investimento...).
        """
        return any(
            jargao_normalizado == SemanticFilter._normalizar(j)
            for j in config.GENERIC_JARGAO
        )

    # ------------------------------------------------------------------
    # NÍVEL 3: REDE DE ARRASTO COM DUPLA VALIDAÇÃO CONTEXTUAL
    # ------------------------------------------------------------------
    def _nivel3_arrasto_dupla_validacao(self, texto_normalizado):
        """
        Palavras amplas (Mercado, Ações, Empresa, Companhia...) disparam
        a rede de arrasto. Porém, se a matéria for pega APENAS por essas
        palavras, ela precisa passar pelo teste de COOCORRÊNCIA com o
        jargão de negócios (bolsa, B3, CVM, IPO, governança...).

        GUARDAS CONTRA FALSO-POSITIVO (Nível 3):
          1. Arrasto genérico ("mercado"/"ações"/"empresa"/"companhia") +
             jargão genérico ("mercado", "empresa", "investimento"...)
             NÃO aprova sem coocorrência de termo inequívoco do mercado
             de capitais — é a porta dos casos "mercado de frutas",
             "ações judiciais", "empresa de limpeza" etc.
          2. Jargões fortes do setor ("bolsa", "B3", "CVM", "IPO",
             "governança") e arrastos específicos continuam aprovando.

        Lógica:
            1. Sem palavra de arrasto -> False.
            2. Sem jargão de negócios -> False.
            3. Se a aprovação vier de arrasto genérico + jargão genérico
               e faltar coocorrência -> descarta.
        """
        tem_palavra_arrasto = False
        ha_arrasto_especifico = False
        primeira_palavra_arrasto = ""
        for palavra in config.PALAVRAS_ARRASTO:
            if self._contem(texto_normalizado, self._normalizar(palavra)):
                tem_palavra_arrasto = True
                if not primeira_palavra_arrasto:
                    primeira_palavra_arrasto = self._normalizar(palavra)
                if not self._eh_arrasto_generico(self._normalizar(palavra)):
                    ha_arrasto_especifico = True
                if ha_arrasto_especifico and primeira_palavra_arrasto:
                    break

        if not tem_palavra_arrasto:
            return False

        for jargao in config.JARGAO_NEGOCIOS:
            if self._contem(texto_normalizado, self._normalizar(jargao)):
                jargao_norm = self._normalizar(jargao)

                # Guarda: jargão GENÉRICO/ambíguo ("ações", "bolsa",
                # "registro", "emissão", "mercado", "investimento"...) — não
                # garante contexto de mercado de capitais por si só (alcança
                # "ações judiciais", "Bolsa Família", "registro civil"...).
                # Exige coocorrência com termo inequívoco do setor.
                if self._eh_jargao_generico(jargao_norm):
                    if not self._tem_coocorrencia_capitais(texto_normalizado):
                        logger.debug(
                            "Nível 3 reprovado: jargão genérico '%s' sem "
                            "coocorrência do mercado de capitais.",
                            jargao,
                        )
                        continue
                    logger.debug(
                        "Nível 3 aprovado pela coocorrência com jargão: '%s'", jargao
                    )
                    return True

                # Jargão forte ("bolsa", "B3", "CVM", "IPO", "governança"...)
                # ou arrasto específico: aprova direto.
                logger.debug(
                    "Nível 3 aprovado pela coocorrência com jargão: '%s'", jargao
                )
                return True

        logger.debug("Nível 3 reprovado: sem jargão de negócios no texto.")
        return False

    # ------------------------------------------------------------------
    # NÍVEL 4: FILTRO NEGATIVO (BLACKLIST — OVERRIDE)
    # ------------------------------------------------------------------
    def _nivel4_blacklist(self, texto_normalizado):
        """
        Verifica a blacklist de ambiguidade. Se QUALQUER palavra barrada
        aparecer, retorna True (FORÇA is_relevante=False).
        """
        for palavra in config.BLACKLIST:
            if self._contem(texto_normalizado, self._normalizar(palavra)):
                logger.info("Blacklist acionada por: '%s'", palavra)
                return True
        return False

    # ------------------------------------------------------------------
    # MÉTODO PRINCIPAL DE AVALIAÇÃO DA MATÉRIA
    # ------------------------------------------------------------------
    def avaliar(self, texto, titulo_resumo=""):
        """
        Avalia uma notícia completa aplicando os Níveis 1 a 4.

        Parâmetros:
            texto (str): o full-text (ou, em última instância, o resumo)
                         da matéria a ser avaliada.
            titulo_resumo (str): título + resumo (superficie editorial).
                         Usado pelo Nível 2 como fonte adicional de âncora
                         quando a matéria é avaliada com full-text.

        Retorna:
            (is_relevante: bool, clientes_citados: list)
        """
        texto_normalizado = self._normalizar(texto)
        titulo_normalizado = self._normalizar(titulo_resumo)

        # ---- NÍVEL 4 (executa PRIMEIRO por causa do override) ----
        if self._nivel4_blacklist(texto_normalizado):
            return (False, [])

        # ---- NÍVEL 1: Citação direta de clientes ----
        clientes = self._nivel1_clientes(texto_normalizado)
        if clientes:
            return (True, clientes)

        # ---- NÍVEL 2: Cenário Macro e Regulatório ----
        if self._nivel2_macro_regulatorio(
            texto_normalizado, titulo_normalizado
        ):
            return (True, [])

        # ---- NÍVEL 3: Rede de arrasto com dupla validação contextual ----
        if self._nivel3_arrasto_dupla_validacao(texto_normalizado):
            return (True, [])

        # ---- Reprovar ----
        return (False, [])
