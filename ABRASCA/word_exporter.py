# =============================================================================
# word_exporter.py
# ----------------
# Módulo WordExporter: geração do documento .docx com a formatação "missão
# crítica" para colagem no WhatsApp (Capítulo 5).
#
# Regras de formatação mais sensíveis:
#   - Cabeçalho rígido: título em negrito (tam. 14), data com _sublinhados_
#     em itálico (tam. 11), depois parágrafo em branco.
#   - Cenário A (sem cliente citado): ▪️ *VEÍCULO* - TÍTULO - LINK
#   - Cenário B (com clientes citados): ▪️ *VEÍCULO com CLIENTES* - TÍTULO - LINK
#   - LINKS: sempre no estilo visual Azul (RGB 0,0,255) e Sublinhado = True.
#   - "Quebra de perna": uma linha em branco ENTRE cada notícia (para não
#     aglutinar na colagem do WhatsApp).
#
# Caminho de salvamento: detecta o usuário do Windows, cria a
# pasta se necessário (os.makedirs) e grava em:
#   C:\Users\<USUARIO>\Desktop\Instainfo Resumos\ABRASCA\
#   Clipping_MercadoCapitais_2026-09-07_14h30.docx
#
# Tratamento de erro (Capítulo 7): se o arquivo estiver aberto no Word
# (PermissionError), alerta o usuário e tenta salvar com sufixo _v2, _v3...
# =============================================================================

import datetime
import logging
import os

import config

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_UNDERLINE

logger = logging.getLogger(__name__)

# MESES em português para a data dinâmica do cabeçalho.
MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


class WordExporter:
    """
    É responsável por transformar a lista de notícias filtradas em um
    documento Word no formato especificado.
    """

    # ------------------------------------------------------------------
    # DATA AMIGÁVEL EM PORTUGUÊS
    # ------------------------------------------------------------------
    @staticmethod
    def _data_em_portugues(data):
        """
        Converte um datetime/date para: "07 de setembro de 2026"
        (mês sempre em minúsculas, conforme o padrão brasileiro).
        """
        return (
            f"{data.day:02d} de {MESES_PT[data.month - 1]} de {data.year}"
        )

    # ------------------------------------------------------------------
    # INTERVALO DE DATAS EM PORTUGUÊS (cabeçalho de janela > 24h)
    # ------------------------------------------------------------------
    @staticmethod
    def _formato_periodo(inicio, fim):
        """
        Converte um intervalo [inicio, fim] para o formato amigável:
          - Mesmo dia            -> "08 de setembro de 2026"
          - Mesmo mês/ano        -> "05 a 08 de setembro de 2026"
          - Mesmo ano            -> "04 de setembro a 06 de outubro de 2026"
          - Anos diferentes      -> "31 de dezembro de 2025 a 02 de janeiro de 2026"
        """
        if inicio.date() == fim.date():
            return WordExporter._data_em_portugues(inicio)
        if inicio.year == fim.year and inicio.month == fim.month:
            return (
                f"{inicio.day:02d} a {fim.day:02d} de "
                f"{MESES_PT[fim.month - 1]} de {fim.year}"
            )
        texto_inicio = f"{inicio.day:02d} de {MESES_PT[inicio.month - 1]}"
        texto_fim = f"{fim.day:02d} de {MESES_PT[fim.month - 1]}"
        if inicio.year == fim.year:
            return f"{texto_inicio} a {texto_fim} de {fim.year}"
        return (
            f"{texto_inicio} de {inicio.year} a {texto_fim} de {fim.year}"
        )

    # ------------------------------------------------------------------
    # DESCOBERTA DO DIRETÓRIO DE SAÍDA
    # ------------------------------------------------------------------
    @staticmethod
    def _descobrir_diretorio_saida():
        """
        Retorna o caminho absoluto onde o .docx deve ser salvo:
        Desktop\\Instainfo Resumos\\ABRASCA\\Resumos diários - ABRASCA\\Relatórios

        A estrutura de pastas de entrega (Relatórios) é criada em runtime
        pelo os.makedirs no fluxo de exportação.
        """
        return config.DIR_RELATORIOS

    # ------------------------------------------------------------------
    # CRIAÇÃO DO CABEÇALHO (Parágrafos 1, 2 e 3)
    # ------------------------------------------------------------------
    @staticmethod
    def _montar_cabecalho(documento, data_execucao, periodo=None, quantidade_materias=None):
        """
        Monta a estrutura rígida do cabeçalho:

        Parágrafo 1: [📈 Resumo de Mercado de Capitais] em NEGRITO, tamanho 14.
        Parágrafo 2: [_07 de setembro de 2026_], OU o intervalo da janela
                     quando informado (ex.: "_05 a 08 de setembro de 2026_"),
                     com os _ nas pontas, em ITÁLICO, tamanho 11.
        Parágrafo 3: quantidade de matérias extraídas logo APÓS a data
                     (ex.: "34 matérias extraídas"), tamanho 11.
        Parágrafo 4: parágrafo em branco (respiro).
        """
        # ---- Parágrafo 1: Título ----
        p1 = documento.add_paragraph()
        run1 = p1.add_run(config.TITULO_DOCUMENTO)  # "📈 Resumo de Mercado de Capitais"
        run1.bold = True
        run1.font.size = Pt(14)

        # ---- Parágrafo 2: Data / período (com _ nas pontas e itálico) ----
        data_formatada = WordExporter._data_em_portugues(data_execucao)
        texto_data = f"_{periodo or data_formatada}_"  # "_07 de setembro de 2026_"

        p2 = documento.add_paragraph()
        run2 = p2.add_run(texto_data)
        run2.italic = True
        run2.font.size = Pt(11)

        # ---- Parágrafo 3: Quantidade de matérias extraídas (após a data) ----
        if quantidade_materias is not None:
            p3 = documento.add_paragraph()
            run3 = p3.add_run(
                WordExporter._texto_quantidade(quantidade_materias)
            )
            run3.font.size = Pt(11)

        # ---- Parágrafo 4: Parágrafo em branco (respiro) ----
        documento.add_paragraph()

    @staticmethod
    def _texto_quantidade(quantidade):
        """
        Texto exibido logo após a data no cabeçalho, ex.:
            "34 matérias extraídas"  |  "1 matéria extraída"
        """
        if quantidade == 1:
            return "1 matéria extraída"
        return f"{quantidade} matérias extraídas"

    # ------------------------------------------------------------------
    # CONCATENAÇÃO DOS CLIENTES CITADOS
    # ------------------------------------------------------------------
    @staticmethod
    def _concatenar_clientes(clientes):
        """
        Junta a lista de clientes citados separados por vírgula,
        conforme o formato dos resumos enviados aos clientes.
        Ex.: ['ABRASCA'] -> "ABRASCA"
        Ex.: ['ABRASCA', 'CVM'] -> "ABRASCA, CVM"
        """
        if not clientes:
            return ""
        return ", ".join(clientes)

    # ------------------------------------------------------------------
    # FORMATAÇÃO DO LINK (Hyperlink REAL + Azul + Sublinhado)
    # ------------------------------------------------------------------
    def _adicionar_hyperlink(self, paragrafo, url, texto=None):
        """
        Adiciona um HYPERLINK REAL (clicável no Word) dentro do parágrafo,
        mantendo a aparência obrigatória: Azul RGB(0,0,255) + Sublinhado.

        O texto do link é a própria URL (quando texto não é informado), e o
        mesmo texto colado no WhatsApp continua virando link normalmente —
        os dois usos ficam atendidos.
        """
        texto = texto if texto is not None else url
        # Registra a relação do hyperlink externo no pacote do documento.
        r_id = paragrafo.part.relate_to(
            url, RT.HYPERLINK, is_external=True
        )
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("r:id"), r_id)

        # Run interno com a formatação visual (azul + sublinhado single).
        novo_run = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        cor = OxmlElement("w:color")
        cor.set(qn("w:val"), "0000FF")
        rpr.append(cor)
        sub = OxmlElement("w:u")
        sub.set(qn("w:val"), "single")
        rpr.append(sub)
        novo_run.append(rpr)

        elemento_texto = OxmlElement("w:t")
        elemento_texto.text = texto
        novo_run.append(elemento_texto)

        hyperlink.append(novo_run)
        paragrafo._p.append(hyperlink)
        return hyperlink

    # ------------------------------------------------------------------
    # MONTAGEM DE UMA NOTÍCIA NO DOCUMENTO
    # ------------------------------------------------------------------
    def _montar_noticia(self, documento, noticia):
        """
        Escreve uma notícia relevante no documento, aplicando o cenário
        A ou B conforme a variável CLIENTES_CITADOS:

        Cenário A (CLIENTES_CITADOS vazio):
            "▪️ *VEÍCULO* - TÍTULO - LINK"
            Ex.: ▪️ Portal UOL - Consumo de energia... - https://is.gd/xkyQI

        Cenário B (CLIENTES_CITADOS com itens):
            "▪️ *VEÍCULO com CLIENTES* - TÍTULO - LINK"
            Ex.: ▪️ *NeoFeed com ABRASCA* - Tokenização coloca o Brasil em
                 novo patamar - https://is.gd/liArN

        Nota: os asteriscos têm significado de negrito do WhatsApp, então
        são mantidos LITERALMENTE no texto (o destinatário verá o negrito
        ao colar no WhatsApp).
        """
        veiculo = noticia["veiculo"]
        titulo = noticia["titulo"]
        link = noticia["link_encurtado"]  # já validado pelo LinkShortener.
        clientes = noticia.get("clientes_citados", [])

        paragrafo = documento.add_paragraph()

        # ---- Emoji ▪️ (marker de listagem) ----
        marker = paragrafo.add_run("▪️ ")
        marker.bold = True

        # ---- Nome do veículo (com clientes no Cenário B) ----
        if clientes:
            # Cenário B: veículo + clientes concatenados dentro dos asteriscos.
            clientes_str = self._concatenar_clientes(clientes)
            rotulo = f"*{veiculo} com {clientes_str}*"
        else:
            # Cenário A: apenas o veículo entre asteriscos.
            rotulo = f"*{veiculo}*"

        run_rotulo = paragrafo.add_run(rotulo)
        run_rotulo.bold = True  # reforço da formatação (além dos asteriscos).

        # ---- Separador: " - " ----
        paragrafo.add_run(" - ")

        # ---- Título da matéria ----
        paragrafo.add_run(titulo)

        # ---- Separador: " - " (antes do link) ----
        paragrafo.add_run(" - ")

        # ---- Link (Azul + Sublinhado + Clicável no Word) ----
        self._adicionar_hyperlink(paragrafo, link)

    # ------------------------------------------------------------------
    # GERADOR PRINCIPAL DO DOCUMENTO
    # ------------------------------------------------------------------
    def exportar(
        self,
        noticias_relevantes,
        horas_passadas=config.DEFAULT_HOURS,
        data_inicio=None,
        data_fim=None,
        quantidade_materias=None,
    ):
        """
        Gera o arquivo .docx completo no caminho de saída.

        Fluxo:
            1. Resolve o diretório de saída (Desktop\\Instainfo Resumos\\ABRASCA).
            2. Cria a pasta se não existir (os.makedirs).
            3. Monta o documento: cabeçalho + notícias (com linha em branco
               ENTRE as matérias — "quebra de perna").
            4. Salva com o nome Clipping_MercadoCapitais_<data>_<hora>.docx.
            5. Se der PermissionError (arquivo aberto no Word), tenta salvar
               com sufixo _v2, _v3, etc.
            6. Retorna o caminho completo do arquivo salvo.
        """
        # ---- Data/hora da extração para nome e cabeçalho ----
        # Sempre no horário de Brasília (independente do fuso da máquina).
        agora = config.agora_brasilia()

        # ---- Cabeçalho com INTERVALO quando a janela é maior que 24h ----
        # Modo calendário (--de/--ate): usa as datas exatas do intervalo.
        # Modo "últimas Nh" (48h/72h/96h...): mostra a cobertura real da janela.
        periodo = None
        if data_inicio is not None and data_fim is not None:
            periodo = WordExporter._formato_periodo(data_inicio, data_fim)
        elif int(horas_passadas) > 24:
            inicio_janela = agora - datetime.timedelta(hours=int(horas_passadas))
            periodo = WordExporter._formato_periodo(inicio_janela, agora)

        # ---- Resolve e cria o diretório de saída ----
        diretorio_saida = self._descobrir_diretorio_saida()
        try:
            os.makedirs(diretorio_saida, exist_ok=True)
            logger.info("Pastas garantidas em: %s", diretorio_saida)
        except OSError as exc:
            logger.error(
                "Não foi possível criar o diretório de saída %s: %s",
                diretorio_saida,
                exc,
            )
            raise

        # ---- Monta o documento Word ----
        documento = Document()

        # Cabeçalho (parágrafos 1 a 4 — rígidos e imutáveis).
        self._montar_cabecalho(
            documento,
            agora,
            periodo=periodo,
            quantidade_materias=quantidade_materias,
        )

        # Notícias relevantes, com linha em branco ENTRE cada uma.
        for indice, noticia in enumerate(noticias_relevantes):
            # Congrega as notícias.
            self._montar_noticia(documento, noticia)

            # "Quebra de perna": linha em branco entre as matérias.
            # (Só adiciona entre matérias, não depois da última.)
            if indice < len(noticias_relevantes) - 1:
                documento.add_paragraph()

        # ---- Nome do arquivo ----
        nome_base = config.ARQUIVO_FORMATO.format(agora)  # Clipping_MercadoCapitais_2026-09-07_14h30.docx
        caminho_arquivo = os.path.join(diretorio_saida, nome_base)

        # ---- Salvamento com tratamento de PermissionError (Capítulo 7) ----
        caminho_final = self._salvar_com_falha_segura(documento, caminho_arquivo)

        return caminho_final

    # ------------------------------------------------------------------
    # SALVAMENTO COM FALHA SEGURA (PermissionError)
    # ------------------------------------------------------------------
    @staticmethod
    def _salvar_com_falha_segura(documento, caminho_arquivo):
        """
        Tenta salvar o documento. Se der PermissionError (arquivo aberto no
        Word), avisa e tenta com sufixo _v2, _v3, até conseguir.

        Retorna o caminho final do arquivo salvo.
        """
        tentativa = 1
        caminho_tentativa = caminho_arquivo

        while True:
            try:
                documento.save(caminho_tentativa)
                logger.info("Arquivo salvo com sucesso: %s", caminho_tentativa)
                return caminho_tentativa
            except PermissionError:
                logger.warning(
                    "Não foi possível salvar '%s' (arquivo provavelmente aberto no Word).",
                    caminho_tentativa,
                )
                tentativa += 1
                # Gera o novo nome: Clipping_MercadoCapitais_2026-09-07_14h30_v2.docx
                raiz, ext = os.path.splitext(caminho_arquivo)
                caminho_tentativa = f"{raiz}_v{tentativa}{ext}"
                if tentativa >= 20:  # Salvaguarda para nunca entrar em loop infinito.
                    logger.error(
                        "Desistindo após várias tentativas de salvar o arquivo."
                    )
                    raise