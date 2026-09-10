# Instainfo Resumos — Motor de Clipping Automatizado

Plataforma de **monitoramento e clipping automatizado de notícias** desenvolvida para a **Instainfo** (assessoria de comunicação). O sistema coleta notícias de dezenas de veículos de imprensa brasileiros, aplica filtragem semântica multi-nível para identificar matérias relevantes para cada cliente e gera relatórios `.docx` prontos para envio via WhatsApp — com links encurtados, destaques de clientes citados e estrutura pensada para copiar e colar direto no mensageiro.

## Para que serve

A Instainfo acompanha diariamente o que a imprensa publica sobre seus clientes e seus setores. Fazer isso manualmente (abrir veículo por veículo, filtrar, montar o resumo e encurtar links) é lento e sujeito a falhas. Este motor **automatiza a cadeia inteira**:

1. **Coleta** as matérias publicadas no período desejado;
2. **Filtra com regras de negócio** o que realmente interessa ao cliente (e veta o que é ruído);
3. **Formata** um relatório legível e já navegável (links clicáveis);
4. **Entrega organizado** em pastas por cliente, com histórico e rastreabilidade.

O operador só precisa escolher o período (horas ou intervalo de datas) e, no módulo genérico, informar a **demanda** (cliente, interesses, veículos). Todo o resto é automático.

---

## Módulos

O projeto evolui de 2 módulos dedicados para um **motor genérico**, cobrindo qualquer cliente ou setor:

| Módulo | Tipo | Foco | Clientes monitorados |
|--------|------|------|----------------------|
| **Energia/** | Dedicado | Setor elétrico brasileiro | ABRADEE, ABIAPE, ABEEólica, ABRAGE, ABiogás, Renova Energia, ABRATE |
| **ABRASCA/** | Dedicado | Mercado de capitais | ABRASCA (Associação Brasileira das Companhias Abertas) |
| **Monitoramento Inteligente/** | Genérico (data-driven) | Qualquer cliente/setor | Definido pela **demanda** (arquivo JSON), sem código novo |

### Monitoramento Inteligente (módulo genérico)

Diferente dos módulos dedicados — que têm clientes, palavras-chave e veículos **fixos no código** — o módulo genérico é dirigido por **demanda**:

- O monitoramento é descrito em um arquivo `demanda.json` (gerado a partir do modelo em `modelos/modelo-demanda.docx` ou `.md`);
- A demanda informa: **cliente**, período **exato**, veículos, **palavras-chave/interesses**, chaves fortes, representantes/variações, termos de contexto e de exclusão;
- Ao rodar, o módulo injeta a demanda no motor (pastas de entrega por cliente, filtros semânticos e termos de busca) e executa o pipeline idêntico ao dos módulos dedicados;
- Qualquer novo cliente ou tema vira **apenas um novo JSON** — nada de código novo.

A matriz semântica genérica é mais simples que a dos módulos dedicados:

- **Nível 1 — Citação do cliente**: nome, variações ou representantes no texto aprovam imediatamente (vira clipping destacado, se habilitado);
- **Nível 2 — Tema por palavras-chave**: aprova com chave **forte**; ou com **2+ keywords** distintas; ou **1 keyword no título**; ou **1 keyword + termo de contexto**. Uma keyword solta, sem contexto, reprova (ex.: "comércio" sozinho em matéria sobre comércio de drogas);
- **Nível 4 — Exclusão (override)**: blacklist global (futebol, crime, clima, reality…) somada aos termos de exclusão da demanda; qualquer um presente **veta a matéria**.

---

## O que o motor faz (pipeline em 6 etapas)

1. **Coleta híbrida** — RSS direto dos veículos + busca interna ("Lupa") em portais WordPress + fallback via Google News com circuit-breaker de rate-limit e cooldown adaptativo;
2. **Pré-filtro rápido** — Descartada na hora a matéria sem nenhum sinal (cliente, keyword, termo de contexto), usando só título + resumo — sem baixar full-text à toa;
3. **Filtragem semântica** — No módulo dedicado, matriz em 4 níveis; no genérico, matriz N1/N2/N4 (ver acima). Sempre sobre o **texto completo** do artigo;
4. **Encurtamento de links** — IS.GD com failover automático para TinyURL e validação HTTP de cada link; se tudo falhar, mantém a URL original;
5. **Exportação Word** — Relatório `.docx` formatado (título, período, itens `▪️ *VEÍCULO* — TÍTULO — LINK`, links azuis sublinhados) pronto para o WhatsApp, mais manifesto `.csv` de rastreabilidade;
6. **Arquivamento** — Relatórios antigos movidos para a subpasta `Arquivo`, mantendo a pasta de entrega só com a entrega mais recente.

### Resiliência de coleta

- **Fallback Scrapling (Plano B)**: quando o `requests` falha (HTTP 403/429/5xx), cai numa página-desafio de anti-bot (Cloudflare) ou o seletor de `<p>` volta vazio, o motor re-baixa o conteúdo com impersonação de TLS/headers de navegador real (via Scrapling). É opcional e de import preguiçoso: sem a dependência instalada, vira *no-op* e o motor segue como antes;
- **Saúde dos feeds**: cada execução registra o estado de cada veículo; após 3 execuções seguidas sem matérias, um alerta é emitido (provável feed morto/bloqueado);
- **Cache persistente de full-text** (JSON, até 4000 entradas): a mesma URL baixada não é re-raspada em runs seguintes — determinismo e menos pressão anti-bot;
- **Fuso horário de Brasília** (UTC-3) em todas as operações, inclusive na regra de janela temporal estrita (só a **data de publicação original** conta).

---

## Destaques técnicos

- **6 workers concorrentes** na coleta e na análise full-text (paralelismo de rede);
- **Google News com proteção**: consultas serializadas com jitter aleatório, cooldown adaptativo (dobra após 429/503) e skip da busca por termo quando o RSS direto já cobre a pauta;
- **Rodízio de User-Agents** reais para contornar paywall/anti-bot básico;
- **Detecção de bloqueio** em resposta HTTP 200 mascarando página-desafio (captcha/`cf-chl`/"just a moment");
- **Monitoramento de saúde** dos feeds com histórico em JSON e alerta após falhas consecutivas;
- **Rotação de logs** (1 por execução, máx. 10 arquivos).
- **ABRASCA**: gates extras de negócio — reprova matérias de origem estrangeira (Nasdaq/NYSE/SEC sem âncora Brasil) e exige âncora de mercado de capitais para termos macroeconômicos amplos.

---

## Estrutura do projeto

```
Instainfo Resumos/
├── Energia/                    # Módulo dedicado — Setor elétrico
│   ├── config.py               #   Configuração central (veículos, clientes, matrizes NLP)
│   ├── main.py                 #   Pipeline principal e CLI (--horas / --de / --ate)
│   ├── scraper.py              #   Coleta (RSS + Google News + Lupa + fallback Scrapling)
│   ├── semantic_filter.py      #   Filtragem semântica em 4 níveis
│   ├── link_shortener.py       #   Encurtamento de links (IS.GD → TinyURL → original)
│   ├── word_exporter.py        #   Geração do relatório .docx + manifesto .csv
│   ├── saude.py                #   Monitoramento de saúde dos feeds
│   ├── requirements.txt        #   Dependências Python
│   └── Resumo Energia - *.bat  #   Atalhos para execução rápida
├── ABRASCA/                    # Módulo dedicado — Mercado de capitais
│   └── (mesma estrutura do Energia)
├── Monitoramento Inteligente/  # Módulo genérico, dirigido por demanda
│   ├── config.py               #   Catálogo de veículos + regras globais (sem cliente fixo)
│   ├── demanda.py              #   Carrega a demanda.json e injeta no motor
│   ├── main.py                 #   Pipeline principal (usa a demanda atual)
│   ├── scraper.py / semantic_filter.py / link_shortener.py / word_exporter.py / saude.py
│   ├── demandas/               #   JSONs de demanda (um por cliente/ocasião)
│   │   └── demanda.json        #   Demanda atual (cliente, palavras-chave, veículos, período)
│   ├── modelos/                #   Modelo de demanda em Word (preencha p/ cada busca)
│   │   └── modelo-demanda.docx
│   ├── rodar.bat               #   Executa o motor com a demanda atual
│   └── requirements.txt
├── .gitignore                  # Ignora __pycache__, Logs/, Cache/, Relatórios/
└── README.md
```

> As entregas (.docx, .csv, logs, cache) **não ficam no repositório** — são gravadas na pasta de entregas do Desktop (ver [Organização das entregas](#organização-das-entregas)).

---

## Requisitos

- Python 3.9+
- Windows (caminhos configurados para `C:\Users\<usuario>\Desktop\Instainfo Resumos - Entregas\<Módulo>`)
- Dependências por módulo em `requirements.txt` (para o fallback anti-bot, instale a linha `scrapling[fetchers]`)

## Instalação

```bash
# Clonar o repositório
git clone https://github.com/victoripolunb-dev/Instainfo-Resumos.git
cd Instainfo-Resumos

# Instalar dependências do módulo desejado
cd Energia
pip install -r requirements.txt

# ABRASCA
cd ../ABRASCA
pip install -r requirements.txt

# Monitoramento Inteligente
cd ../"Monitoramento Inteligente"
pip install -r requirements.txt
```

## Uso

### Energia / ABRASCA (módulos dedicados)

```bash
python main.py                     # pergunta quantas horas (padrão: 24)
python main.py --horas 48          # últimas 48 horas
python main.py --horas 96          # últimas 96 horas
python main.py --de 04/09/2026 --ate 08/09/2026   # intervalo de datas
python main.py --nao-arquivar      # não move relatórios antigos para Arquivo
python main.py --sem-cache         # ignora o cache de full-text
```

Atalhos `.bat` na pasta do Energia: `Resumo Energia - 24h/48h/72h/96h.bat` e `Resumo Energia - Por data.bat`.

### Monitoramento Inteligente (módulo genérico)

1. Preencha as cópias do modelo em `modelos/modelo-demanda.docx` (ou `.md`) — cliente, contexto, período exato, veículos e interesses;
2. Converta o preenchimento em `demandas/demanda.json` (campos: `cliente`, `contexto`, `data_inicio`, `data_fim`, `veiculos`, `palavras_chave`, `palavras_chave_fortes`, `termos_contexto`, `termos_exclusao`, `destacar_clipping`, `variacoes`, `representantes`);
3. Rode o motor:

```bash
python main.py                              # usa demandas/demanda.json (demanda atual)
python main.py --demanda C:\caminho\demanda.json   # outra demanda
python main.py --de 08/09/2026 --ate 10/09/2026    # sobrepõe a janela da demanda
python main.py --horas 48                   # últimas 48h (ignora as datas da demanda)
python main.py --nao-arquivar
python main.py --sem-cache
```

Ou use o atalho `rodar.bat` (aceita os mesmos argumentos).

---

## Organização das entregas

As entregas ficam no Desktop, **fora do repositório**, em `C:\Users\<usuario>\Desktop\Instainfo Resumos - Entregas\`:

```
Instainfo Resumos - Entregas/
├── Energia/
│   ├── Entregas/                      # cópias prontas para envio
│   └── Resumos diários - Energia/
│       ├── Relatórios/                # clipping mais recente (.docx + .csv)
│       │   └── Arquivo/               # históricos movidos automaticamente
│       ├── Logs/                      # execucao.log + saude_feeds.json
│       └── Cache/                     # cache persistente de full-text
├── ABRASCA/
│   └── (mesma organização)
└── Monitoramento Inteligente/
    ├── Entregas/
    │   └── <Cliente da demanda>/      # Relatórios/, Arquivo/, Logs/, Cache/ por cliente
    └── Modelos/                       # modelo-demanda.md e .docx (para novo monitoramento)
```

Regra importante do filtro temporal: uma matéria **publicada antes do recorte** (e apenas **atualizada** dentro dele) é descartada; **publicada dentro** do recorte é mantida — a data de atualização nunca decide. A regra é conferida pela data original extraída do HTML (`article:published_time`).

---

## Catálogo de veículos

O catálogo completo e os apelidos aceitos vivem em `Monitoramento Inteligente/config.py` (`CATALOGO_VEICULOS` e `ALIASES_VEICULOS`) — que unifica os módulos Energia + ABRASCA + G1 + JOTA:

| Mídia Geral | Setor Elétrico |
|-------------|----------------|
| Valor Econômico | CanalEnergia |
| Estadão | MegaWhat |
| Estadão \| Broadcast | Cenário Energia |
| Estadão \| E-Investidor | Canal Solar |
| Folha de S. Paulo | Brasil Energia |
| O Globo | Agência Eixos |
| G1 | Agência iNFRA |
| Poder 360 | |
| CNN Brasil | |
| Metrópoles | |
| Veja | |
| Portal UOL | |
| Portal JOTA | |
| Brazil Journal | |
| InfoMoney | |
| Portal Exame | |
| Correio Braziliense | |
| BR Investing | |
| NeoFeed | |
| Agência Brasil | |

Veículos sem RSS funcional (Veja, Correio Braziliense, BR Investing) usam fallback Google News. Portais WordPress com busca interna ("Lupa") são usados para coleta direcionada por termo: Canal Solar, NeoFeed, Brazil Journal, Brasil Energia, Cenário Energia.

---

## Licença

Uso interno — Instainfo.