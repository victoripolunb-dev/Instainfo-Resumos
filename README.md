# Instainfo Resumos — Motor de Clipping de Notícias

Sistema automatizado de **clipping de notícias** para monitoramento de veículos de comunicação brasileiros, com foco em dois módulos independentes:

| Módulo | Foco | Clientes |
|--------|------|----------|
| **Energia** | Setor elétrico brasileiro | ABRADEE, ABIAPE, ABEEólica, ABRAGE, ABiogás, Renova Energia, ABRATE |
| **ABRASCA** | Mercado de capitais | ABRASCA |

---

## Como funciona

O pipeline completo (executado via `python main.py`) segue estas etapas:

1. **Coleta** — RSS direto de 18 veículos + busca interna (Lupa) em portais WordPress + fallback via Google News
2. **Pré-filtro rápido** — Descarta matérias claramente irrelevantes usando apenas título e resumo do RSS
3. **Análise semântica (Níveis 1–4)** — Avalia o texto completo com matriz de filtragem:
   - **Nível 1**: Clientes-alvo (nome, sigla, líderes)
   - **Nível 2**: Chaves macro e regulatórias (ANEEL, MME, leilões, etc.)
   - **Nível 3**: Rede de arrasto com dupla validação contextual
   - **Nível 4**: Blacklist de ambiguidade (esportes, saúde, automotivo, etc.)
4. **Encurtamento de links** — IS.GD com failover para TinyURL
5. **Exportação** — Gera relatório `.docx` formatado para WhatsApp + manifesto `.csv`

---

## Estrutura do projeto

```
Instainfo Resumos/
├── Energia/
│   ├── config.py              # Configuração central (veículos, clientes, matrizes NLP)
│   ├── main.py                # Pipeline principal e CLI
│   ├── scraper.py             # Coleta de notícias (RSS + Google News + Lupa)
│   ├── semantic_filter.py     # Filtragem semântica em 4 níveis
│   ├── link_shortener.py      # Encurtamento de links (IS.GD / TinyURL)
│   ├── word_exporter.py       # Geração do relatório .docx
│   ├── saude.py               # Monitoramento de saúde dos feeds
│   ├── requirements.txt       # Dependências Python
│   └── Resumo Energia - *.bat # Atalhos para execução rápida
├── ABRASCA/
│   ├── (mesmos módulos)
│   └── requirements.txt
├── .gitignore
└── README.md
```

---

## Requisitos

- Python 3.9+
- Windows (caminhos configurados para `C:\Users\<usuario>\Desktop\Instainfo Resumos`)

## Instalação

```bash
# Clonar o repositório
git clone https://github.com/<seu-usuario>/instainfo-resumos.git
cd instainfo-resumos

# Instalar dependências (para o módulo desejado)
cd Energia
pip install -r requirements.txt

# Ou para ABRASCA:
cd ../ABRASCA
pip install -r requirements.txt
```

## Uso

### Modo interativo (pergunta quantas horas)
```bash
python main.py
```

### Últimas N horas
```bash
python main.py --horas 24
python main.py --horas 48
python main.py --horas 72
```

### Por intervalo de datas
```bash
python main.py --de 04/09/2026 --ate 08/09/2026
```

### Opções extras
```bash
--nao-arquivar    # Não mover relatórios antigos para a pasta Arquivo
--sem-cache       # Ignorar cache de full-text (forçar novo scraping)
```

### Atalhos (.bat)
Na pasta de cada módulo há arquivos `.bat` para execução rápida:
- `Resumo Energia - 24h.bat` — Últimas 24 horas
- `Resumo Energia - 48h.bat` — Últimas 48 horas
- `Resumo Energia - 72h.bat` — Últimas 72 horas
- `Resumo Energia - 96h.bat` — Últimas 96 horas
- `Resumo Energia - Por data.bat` — Modo calendário

---

## Veículos monitorados (18 fontes)

| Mídia Geral | Setor Elétrico |
|-------------|----------------|
| Valor Econômico | CanalEnergia |
| Estadão | MegaWhat |
| Folha de S. Paulo | Cenário Energia |
| O Globo | Canal Solar |
| Estadão \| Broadcast | Brasil Energia |
| NeoFeed | Agência Eixos |
| Brazil Journal | |
| Metrópoles | |
| CNN Brasil | |
| Agência iNFRA | |
| Poder 360 | |
| Portal UOL | |

---

## Licença

Uso interno — Instainfo.
