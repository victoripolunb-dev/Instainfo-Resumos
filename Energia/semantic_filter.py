# =============================================================================
# semantic_filter.py
# ------------------
# Módulo SemanticFilter: o CÉREBRO do sistema.
#
# Implementa a matriz de busca semântica e NLP (Capítulo 3) com 4 níveis de
# validação lógica:
#
#   Nível 1: Citação Direta (Alvos Primários - os 7 clientes)
#   Nível 2: Cenário Macro e Regulatório (15 chaves compostas)
#   Nível 3: Rede de Arrasto com Dupla Validação Contextual
#   Nível 4: Filtro Negativo (Blacklist de Ambiguidade) — OVERRIDE total
#
# A classe recebe o full-text de uma matéria e devolve:
#   is_relevante   -> bool (matéria passa ou não)
#   clientes_citados -> lista de clientes encontrados (Nível 1)
#
# A blacklist REMOVE a matéria da fila de forma incondicional, mesmo que
# uma citação direta (Nível 1) tenha sido encontrada. Isso garante o
# "override" especificado no Capítulo 3.4.
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
        """Inicializa o filtro semântico. Não há estado interno acumulado,
        pois cada matéria é avaliada de forma independente."""
        pass

    # ------------------------------------------------------------------
    # UTILITÁRIOS DE TEXTO
    # ------------------------------------------------------------------
    @staticmethod
    def _normalizar(texto):
        """
        Normaliza o texto para busca case-insensitive segura:
          - converte para minúsculas
          - remove acentos (para capturar variações tipo ABEEolica/ABEEólica)
        Retorna string normalizada.
        """
        from unicodedata import normalize

        texto = texto or ""
        texto = texto.lower()

        # Remove acentos: normalize NFD separa os acentos dos caracteres,
        # e o join abaixo remove apenas as marcas de combinação (Mn).
        texto = normalize("NFD", texto)
        texto = "".join(c for c in texto if not __import__("unicodedata").combining(c))
        return texto

    @staticmethod
    def _contem(texto_normalizado, termo):
        """
        Verifica se 'termo' está presente no texto (já normalizado).
        Usa busca por palavra inteira (word boundary) quando possível,
        evitando falsos positivos de prefixos (ex.: "GD" não casa com "GDP").
        """
        # Termos compostos (com espaço) ou siglas curtas quebram o \b.
        # Para siglas de 2-3 letras (GD, ONS, MME), exigimos fronteiras para
        # não capturar "GDP", "Oficina", etc.
        if len(termo) <= 3:
            # Usa lookahead/lookbehind para forçar fronteira de palavra.
            return re.search(rf"(?<![a-z0-9]){re.escape(termo)}(?![a-z0-9])", texto_normalizado) is not None
        # Para termos maiores, busca substring simples (segura o suficiente).
        return termo in texto_normalizado

    # ------------------------------------------------------------------
    # NÍVEL 1: CITAÇÃO DIRETA (Clientes)
    # ------------------------------------------------------------------
    def _nivel1_clientes(self, texto_normalizado):
        """
        Procura os nomes exatos (case-insensitive) das 7 entidades no texto.

        Cada cliente possui um conjunto de variações/sinônimos (config.CLIENTES).
        Se o texto contiver QUALQUER variação dele, o cliente é considerado
        citado.

        Retorna: lista dos clientes citados (nomes oficiais de exibição).
        """
        citados = []
        for cliente, variacoes in config.CLIENTES.items():
            for variacao in variacoes:
                if self._contem(texto_normalizado, self._normalizar(variacao)):
                    # Evita duplicar o mesmo cliente na lista.
                    if cliente not in citados:
                        citados.append(cliente)
                    break  # Achou o cliente, não precisa testar as demais variações.
        return citados

    # ------------------------------------------------------------------
    # NÍVEL 2: CENÁRIO MACRO E REGULATÓRIO
    # ------------------------------------------------------------------
    def _nivel2_macro_regulatorio(self, texto_normalizado):
        """
        Procura as chaves compostas do monitoramento institucional.
        Retorna True se qualquer chave do config.CHAVES_NIVEL2 aparecer.
        """
        for chave in config.CHAVES_NIVEL2:
            if self._contem(texto_normalizado, self._normalizar(chave)):
                logger.debug("Nível 2 acionado pela chave: '%s'", chave)
                return True
        return False

    @staticmethod
    def _eh_jargao_tarifa(jargao_normalizado):
        """
        True se o jargão for a família "tarifa/tarifas/tarifária".
        Esses termos são ambíguos: podem se referir a tarifas do setor
        elétrico OU a tarifas alfandegárias / comércio exterior.
        """
        return jargao_normalizado.startswith("tarif")

    def _tem_coocorrencia_setor_eletrico(self, texto_normalizado):
        """
        Verifica se há coocorrência com ao menos um termo inequívoco do
        setor elétrico (config.TERMOS_COOCORRENCIA_SETOR_ELETRICO).
        Sem isso, uma aprovação apoiada apenas em arrastos genéricos +
        jargão genérico NÃO pode passar (ex.: tarifa de comércio exterior).
        """
        for termo in config.TERMOS_COOCORRENCIA_SETOR_ELETRICO:
            if self._contem(texto_normalizado, self._normalizar(termo)):
                return True
        return False

    @staticmethod
    def _eh_arrasto_generico(palavra_normalizada):
        """
        Arrastos genéricos: "energia", "elétrica"/"elétrico" — comuns demais
        para, sozinhos, garantir contexto do setor elétrico (ex.: "Elétrica"
        casa por substring com "hidrelétrica" em matérias de resgate).
        """
        return any(
            palavra_normalizada == SemanticFilter._normalizar(g)
            for g in config.GENERIC_ARRASTO
        )

    @staticmethod
    def _eh_jargao_generico(jargao_normalizado):
        """
        Jargões de negócios FRACOS/genéricos — não garantem contexto do
        setor elétrico (setor, governo, mercado, investimento, tarifas...).
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
        Palavras amplas (Energia, Elétrica, Eólica, Solar...) disparam a rede
        de arrasto. Porém, se a matéria for pega APENAS por essas palavras,
        ela precisa passar pelo teste de COOCORRÊNCIA com o jargão de negócios
        (setor, governo, investimento, mercado, tarifas, MW, B3, ...).

        GUARDAS CONTRA FALSO-POSITIVO (Nível 3):
          1. "tarifa/tarifas/tarifária" sozinha NÃO aprova — exige coocorrência
             de termo inequívoco do setor elétrico (comércio exterior disfarça).
          2. ArrAlgo genérico ("energia"/"elétrica"/"elétrico") + jargão
             genérico ("setor", "governo", "mercado", "investimento"...)
             NÃO aprova sem coocorrência elétrica — é a porta dos casos
             "exportações da Itália", resgates em usinas, agronegócio etc.
          3. Jargões fortes do setor ("geração", "transmissão", "MW", "leilão")
             e arrastos específicos ("eólica", "solar") continuam aprovando.

        Lógica:
            1. Sem palavra de arrasto -> False.
            2. Sem jargão de negócios -> False.
            3. Se a aprovação vir de salsa fraca (tarifa ou arrasto genérico
               + jargão genérico) e faltar coocorrência elétrica -> descarta.
        """
        # Passo 1: captura o arrasto (guarda o primeiro que aparecer e se
        # existe algum arrasto ESPECÍFICO — "solar"/"eólica" — que dispensam
        # a exigência de coocorrência por já serem código do setor).
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
                    # Não precisa continuar: arrasto específico já garante setor.
                    break

        if not tem_palavra_arrasto:
            return False

        # Passo 2 (revisado): percorre o jargão; cada candidato passa pela
        # dupla validação contextual antes de aprovar.
        for jargao in config.JARGAO_NEGOCIOS:
            if self._contem(texto_normalizado, self._normalizar(jargao)):
                jargao_norm = self._normalizar(jargao)

                # Guarda 1: tarifa em contexto NÃO elétrico (comércio exterior).
                if self._eh_jargao_tarifa(jargao_norm):
                    if not self._tem_coocorrencia_setor_eletrico(texto_normalizado):
                        logger.debug(
                            "Nível 3 reprovado: 'tarifa' sem coocorrência "
                            "com o setor elétrico (provável comércio exterior)."
                        )
                        continue
                    logger.debug(
                        "Nível 3 aprovado pela coocorrência com jargão: '%s'", jargao
                    )
                    return True

                # Guarda 2: arrasto genérico (sem arrasto específico) +
                # jargão genérico — precisa de coocorrência inequívoca do
                # setor elétrico.
                if (
                    not ha_arrasto_especifico
                    and self._eh_arrasto_generico(primeira_palavra_arrasto)
                    and self._eh_jargao_generico(jargao_norm)
                ):
                    if not self._tem_coocorrencia_setor_eletrico(texto_normalizado):
                        logger.debug(
                            "Nível 3 reprovado: arrasto genérico '%s' + jargão "
                            "genérico '%s' sem coocorrência do setor elétrico.",
                            primeira_palavra_arrasto, jargao,
                        )
                        continue
                    logger.debug(
                        "Nível 3 aprovado pela coocorrência com jargão: '%s'", jargao
                    )
                    return True

                # Jargão forte (geração, transmissão, MW, leilão, ...) ou
                # arrasto específico (eólica/solar): aprova direto.
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
        aparecer, retorna True (isso FORÇA is_relevante=False e remove a
        matéria da fila, independente do resultado dos níveis 1-3).
        """
        for palavra in config.BLACKLIST:
            if self._contem(texto_normalizado, self._normalizar(palavra)):
                logger.info("Blacklist acionada por: '%s'", palavra)
                return True
        return False

    # ------------------------------------------------------------------
    # MÉTODO PRINCIPAL DE AVALIAÇÃO DA MATÉRIA
    # ------------------------------------------------------------------
    def avaliar(self, texto):
        """
        Avalia uma notícia completa aplicando os Níveis 1 a 4.

        Parâmetros:
            texto (str): o full-text (ou, em última instância, o resumo)
                         da matéria a ser avaliada.

        Retorna:
            (is_relevante: bool, clientes_citados: list)
        """
        texto_normalizado = self._normalizar(texto)

        # ---- NÍVEL 4 (executa PRIMEIRO por causa do override) ----
        # A blacklist tem poder maior sobre todas as etapas. Se a matéria
        # tem palavra barrada, ela morre aqui, independentemente de citar
        # ABRADEE ou conter 'leilão'.
        if self._nivel4_blacklist(texto_normalizado):
            return (False, [])

        # ---- NÍVEL 1: Citação direta de clientes ----
        clientes = self._nivel1_clientes(texto_normalizado)
        if clientes:
            # Encontrou cliente citado diretamente -> RELEVANTE.
            return (True, clientes)

        # ---- NÍVEL 2: Cenário Macro e Regulatório ----
        if self._nivel2_macro_regulatorio(texto_normalizado):
            # Relevante para monitoramento institucional, mas sem cliente citado.
            return (True, [])

        # ---- NÍVEL 3: Rede de arrasto com dupla validação contextual ----
        if self._nivel3_arrasto_dupla_validacao(texto_normalizado):
            return (True, [])

        # ---- Reprovar ----
        return (False, [])