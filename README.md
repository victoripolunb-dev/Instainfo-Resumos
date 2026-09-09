# Instainfo Resumos — Motor de Clipping Automatizado

Plataforma de **monitoramento e clipping automatizado de notícias** desenvolvida para a **Instainfo** (assessoria de comunicação). O sistema coleta notícias de 18 veículos de imprensa brasileiros, aplica filtragem semântica multi-nível para identificar matérias relevantes para cada cliente e gera relatórios `.docx` prontos para envio via WhatsApp.

## O que faz

O pipeline completo coleta, filtra e exporta notícias em 6 etapas:

1. **Coleta híbrida** — RSS direto de 18 veículos (Valor Econômico, Estadão, Folha, O Globo, CNN Brasil, etc.) + busca interna (Lupa) em portais WordPress + fallback via Google News
2. **Pré-filtro rápido** — Descarta matérias irrelevantes usando apenas título e resumo do RSS, sem baixar o texto completo
3. **Filtragem semântica em 4 níveis** — Analisa o texto completo do artigo:
   - **Nível 1** (menção direta): Nome, sigla ou líderes dos clientes-alvo → aprovação imediata
   - **Nível 2** (cenário macro/regulatório): Chaves setoriais como ANEEL, MME, leilões de energia, CVM, IPO, B3
   - **Nível 3** (rede de arrasto): Palavras amplas do setor + validação contextual cruzada com jargão de negócio
   - **Nível 4** (blacklist): Veto automático para esportes, saúde, automotivo, entretenimento, astrologia, etc.
4. **Encurtamento de links** — IS.GD com failover para TinyURL, validação HTTP em cada link
5. **Exportação Word** — Relatório `.docx` formatado com negrito, links clicáveis e estrutura pronta para copiar e colar no WhatsApp
6. **Arquivamento** — Manifesto `.csv` + movimentação de relatórios antigos para pasta de arquivo

## Módulos

| Módulo | Foco | Clientes monitorados |
|--------|------|----------------------|
| **Energia/** | Setor elétrico brasileiro | ABRADEE, ABIAPE, ABEEólica, ABRAGE, ABiogás, Renova Energia, ABRATE |
| **ABRASCA/** | Mercado de capitais | ABRASCA (Associação Brasileira das Companhias Abertas) |

## Destaques técnicos

- **6 workers concorrentes** para coleta e análise de texto
- **Cache persistente** de full-text (JSON, até 4000 entradas) para evitar scraping repetido
- **Proteção contra rate-limit** no Google News com circuit-breaker e cooldown adaptativo
- **Fuso horário de Brasília** (UTC-3) em todas as operações
- **Monitoramento de saúde** dos feeds (alerta após 3 falhas consecutivas)

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
