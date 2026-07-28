# Plan — Vasco Digest Bot

Plano técnico para `spec.md`. Leia `research.md` antes — ele justifica as
decisões daqui.

---

## 1. Princípios

1. **Determinístico antes de probabilístico.** Regra pega o que dá; LLM decide o resto.
2. **Pipeline como função pura por etapa.** Modelos Pydantic entram e saem.
3. **CLI primeiro.** Toda execução é `vascobot run`. Cron/Dagster só chamam.
4. **Tudo plugável nas bordas.** Fonte, plataforma e LLM são interfaces.
5. **Falhar por componente, não por execução.**
6. **Custo é observável.** O X projeta e registra gasto a cada run.
7. **Nada de texto de terceiro literal.**

---

## 2. Stack

| Camada | Escolha |
|---|---|
| Linguagem | Python 3.12, `uv` |
| Modelos | `pydantic` v2 + `pydantic-settings` |
| HTTP | `httpx` (async) |
| Parsing | `feedparser`, `selectolax`, `trafilatura` |
| Dedup | `rapidfuzz` + `unidecode` |
| Persistência | **SQLite** (stdlib, SQL cru, sem ORM) |
| LLM | **Ollama Cloud** via `ollama` |
| Publishers | `atproto` (Bluesky), `httpx` (X) |
| CLI / Log / Testes | `typer` / `structlog` / `pytest` + `respx` |
| Runtime | Docker + cron |

**Por que SQLite:** o estado é OLTP — escritas pequenas, leitura por chave,
constraint UNIQUE para idempotência. DuckDB e Delta são colunares, errados para
tabela de controle de bot. Para analisar histórico depois, exporte Parquet e
abra no DuckDB. Não misture os papéis.

---

## 3. Arquitetura

```
   cron (BRT) ──► vascobot run
                       │
   ┌───────────────────▼─────────────────────────────┐
   │ 1. COLLECT    sources/*  → RawArticle[]          │ ← watermark por fonte
   │ 2. NORMALIZE  trafilatura → Article[]            │
   │ 3. CLASSIFY   exclusão → regra → LLM             │ ← LLMProvider
   │ 4. DEDUPE     rapidfuzz + entidade → Cluster[]   │
   │ 5. SUMMARIZE  LLM por categoria → Digest[]       │ ← LLMProvider
   │ 6. COMPOSE    por plataforma ativa → PostDraft[] │ ← publisher registry
   │ 7. PUBLISH    Bluesky ∥ X (independentes)        │
   └───────────────────┬─────────────────────────────┘
                       ▼
                    SQLite
```

---

## 4. Estrutura do repositório

```
vascobot/
├── pyproject.toml · Dockerfile · docker-compose.yml · crontab · .env.example
├── specs/001-vasco-digest/{spec,plan,research,tasks}.md
├── src/vascobot/
│   ├── cli.py · config.py · models.py · db.py · logging.py
│   ├── sources/       base.py · registry.py · netvasco.py · supervasco.py
│   ├── llm/           base.py · ollama_cloud.py · schemas.py
│   ├── pipeline/      collect.py · normalize.py · rules.py · classify.py
│   │                  dedupe.py · priority.py · summarize.py · guardrails.py
│   │                  compose.py
│   ├── publishers/    base.py · registry.py · bluesky.py · x.py · cost.py
│   └── prompts/       classify.md · summarize.md
├── tests/fixtures/ · tests/test_*.py
└── data/vascobot.db
```

---

## 5. Modelo de dados

```sql
CREATE TABLE runs (
  id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
  window_start TEXT NOT NULL, window_end TEXT NOT NULL,
  status TEXT NOT NULL,            -- running|ok|partial|failed
  stats_json TEXT
);

CREATE TABLE source_state (
  source_id TEXT PRIMARY KEY, watermark_ts TEXT, watermark_extid TEXT,
  last_ok_at TEXT, last_error TEXT
);

CREATE TABLE articles (
  id TEXT PRIMARY KEY,             -- sha256(url_canonica)
  source_id TEXT NOT NULL, external_id TEXT,
  url TEXT NOT NULL UNIQUE, title TEXT NOT NULL, summary TEXT, body TEXT,
  published_at TEXT NOT NULL, fetched_at TEXT NOT NULL, content_hash TEXT NOT NULL,
  category TEXT, confidence REAL,
  classify_method TEXT,            -- rule_exclusion|rule_positive|llm
  llm_model TEXT,
  status TEXT NOT NULL,            -- ok|pending_review
  cluster_id TEXT, run_id TEXT NOT NULL
);
CREATE INDEX idx_articles_cat ON articles(category, published_at);

CREATE TABLE clusters (
  id TEXT PRIMARY KEY, canonical_article_id TEXT NOT NULL,
  category TEXT NOT NULL, size INTEGER NOT NULL, run_id TEXT NOT NULL
);

CREATE TABLE digests (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL, category TEXT NOT NULL,
  headline TEXT NOT NULL, bullets_json TEXT NOT NULL,
  source_urls_json TEXT NOT NULL, llm_model TEXT,
  UNIQUE(run_id, category)
);

CREATE TABLE posts (
  id TEXT PRIMARY KEY, digest_id TEXT NOT NULL,
  platform TEXT NOT NULL,          -- x|bluesky
  thread_index INTEGER NOT NULL, text TEXT NOT NULL, has_link INTEGER NOT NULL,
  status TEXT NOT NULL,            -- pending|approved|published|failed|skipped
  external_id TEXT, cost_usd REAL DEFAULT 0,
  published_at TEXT, error TEXT,
  idempotency_key TEXT NOT NULL UNIQUE
);
```

---

## 6. Decisões de design

### 6.1 Source Adapter

```python
class SourceAdapter(ABC):
    source_id: str
    base_url: str
    rate_limit_rps: float = 0.5

    @abstractmethod
    async def discover(self, since: Watermark) -> list[RawArticle]: ...
    async def hydrate(self, raw: RawArticle) -> Article: ...  # default: trafilatura
```

**Watermark duplo:** onde há ID sequencial (NetVasco `/n/{id}/`, SuperVasco
`-{id}.html`), o ID é o watermark primário e o timestamp o secundário. IDs
sequenciais são imunes a fuso e a republicação com data alterada.

### 6.2 Classificação — três camadas

```
Camada 0 — EXCLUSÃO (regex, primeiro, sempre)
  ^(futsal|basquete|vôlei|volei|natação|remo|atletismo|judô|
    e-sports|esports|futmesa|futevôlei|polo aquático|esporte amador)\b
  | ^sub-(0[0-9]|1[0-4]):            → Sub-14 e menores
  → descartado, confiança 1.0, NUNCA vai ao LLM

Camada 1 — REGRA POSITIVA (prefixo + editoria + URL)
  ^feminino:                    → feminino
  ^sub-20: | \bsub-20\b         → base_sub20
  ^sub-1[67]: | \bsub-1[67]\b   → base_sub17      (D3: Sub-16 junto)
  ^sub-15: | \bsub-15\b         → base_sub15
  url ~ /editoria/categorias-de-base/ → base_* (idade pelo texto)
  → confiança 0.95

Camada 2 — LLM  ← carrega ~60% do volume (D5)
  Decide entre as 6 categorias. Não é fallback: é o julgamento principal
  para tudo que vem sem prefixo. Recebe título + lide + editoria + URL.
```

Limiar: `confidence >= 0.7` publica; abaixo → `pending_review`.

> A ordem importa. `Futsal Feminino Base: ...` **precisa** morrer na camada 0,
> senão a camada 1 o classifica como `feminino`.

**D11 entra aqui:** o prompt recebe `INCLUDE_INSTITUTIONAL`. Com `true`
(padrão), notícia sobre SAF, CEO, investidor, eleição, patrocínio, estádio e
sócio-torcedor é classificada como `profissional`. Continuam em `descartado`:
notas de torcida organizada, efeméride/história e blog de opinião. Trocar a flag
muda o comportamento sem alterar código.

### 6.3 Interface de LLM

```python
class LLMProvider(ABC):
    @abstractmethod
    async def structured(
        self, prompt: str, schema: type[BaseModel], model: str, temperature: float = 0
    ) -> BaseModel: ...
```

Implementação `OllamaCloudProvider`:
- `format=Schema.model_json_schema()` — o Ollama valida o schema **durante a
  decodificação** (research.md §4.2). Passar o schema também no prompt.
- `temperature=0`
- Retry 3× com backoff; `OLLAMA_API_KEY` por env.
- Batch de até 20 manchetes por chamada na classificação.

Trocar para Ollama local = mudar `OLLAMA_HOST`. Nenhuma outra linha muda —
relevante porque o deploy (D7) ainda pode virar homelab.

**Seleção de modelo é medição, não palpite.** Ver T-016b: rodar os candidatos
contra o CSV rotulado e escolher pelo resultado.

### 6.4 Deduplicação

Dentro de cada categoria:
1. **Exato:** mesma URL canônica ou mesmo `content_hash`.
2. **Near-dup:** normalizar título (lower → `unidecode` → remover prefixo →
   remover stopwords pt-BR → ordenar tokens) → `rapidfuzz.token_set_ratio >= 85`.
3. **Ancoragem por entidade:** exigir ≥ 1 token capitalizado em comum. Evita
   agrupar "Vasco vence o Bahia" com "Vasco vence o Santos".

Clustering guloso — O(n²) é irrelevante com n < 100. Canônico = o mais antigo.

### 6.5 Sumarização e guardrails

Uma chamada por categoria. Entrada: título + lide + ~800 chars do corpo de cada
artigo canônico. Saída via structured output:

```python
class ResumoCategoria(BaseModel):
    headline: str  # ≤ 80 chars
    bullets: list[str]  # ≤ 140 chars cada, máx. 2
```

Regras do prompt: só o que está no material; especulação sempre marcada e
atribuída ("segundo X", "apurou"); sem trecho literal > 10 palavras; sem
adjetivo torcedor; material insuficiente → `bullets: []`.

**Priorização (RF-13).** Com o institucional incluído, `profissional` concentra
o maior volume e a thread só comporta ~2 bullets. Ordenar os clusters por peso
**antes** de cortar — 1 jogo/elenco/lesão, 2 mercado confirmado/comissão,
3 mercado especulado, 4 institucional. Empate → mais recente primeiro. Peso 4
nunca desloca peso 1. A classificação de peso é determinística por palavra-chave,
não sai do LLM: é regra auditável em `pipeline/priority.py`.

**Guardrail pós-LLM** (`guardrails.py`), roda sempre:
- rejeita bullet com ≥ 10 palavras consecutivas idênticas ao corpo-fonte;
- rejeita nome próprio que não apareça em nenhum artigo do cluster;
- rejeita bullet acima do limite de caracteres.

Rejeição → `pending_review`, nunca publica silenciosamente.

### 6.6 Composição — thread nas duas plataformas (D4)

| | Bluesky | X |
|---|---|---|
| Limite | 300 graphemes | 280 chars (25.000 se Premium) |
| Estrutura | raiz + bullets + fontes | idem |
| Máx. posts | 4 | 4 |
| Links | sempre (grátis) | conforme `X_LINK_POLICY` |

Contar **graphemes** no Bluesky (`regex` com `\X`), não `len()`. No X, weighted
character count — URL sempre conta 23.

```
🔵⚫ {emoji} {CATEGORIA} — {HH:MM}
{headline}
```

### 6.7 Publishers e desacoplamento do X (RF-07)

```python
class Publisher(ABC):
    platform: str
    enabled: bool

    async def publish_thread(self, drafts: list[PostDraft]) -> list[PublishedPost]: ...
```

`publishers/registry.py` monta a lista **a partir da config**. O pipeline itera
sobre publishers ativos e nunca referencia "X" por nome.

`X_ENABLED=false` corta o X **já no compose** — não gera draft órfão. A coluna
`platform` em `posts` mantém o histórico íntegro e a idempotência por
plataforma. Desligar é uma variável de ambiente e um restart.

Segundo interruptor, automático: se `X_MONTHLY_BUDGET_USD` estiver definido e
for estourado, o publisher do X marca `skipped` e loga alerta — sem exceção,
sem afetar o Bluesky. Com a variável vazia (D8), só registra o gasto.

**Custo (`publishers/cost.py`):** tarifa por post detectando presença de URL
(research.md §3). A cada run, logar gasto do run + acumulado do mês + projeção
mensal. Isso é o que vai permitir decidir D8 com número real.

### 6.8 Agendamento

`cron` no container, `TZ=America/Sao_Paulo`:

```cron
0 0,6,9,12,15,18,21 * * * /app/.venv/bin/vascobot run >> /var/log/vascobot.log 2>&1
```

**Não usar Dagster ainda:** para um job de 3 minutos ele traz daemon, banco de
metadata e webserver — infra maior que a aplicação. Como tudo é CLI, migrar
depois é escrever um `@op` que chama `run()`. Quando quiser backfill por
partição horária e retry declarativo, aí passa a valer (Fase 5).

**Não usar GitHub Actions:** cron atrasa de forma imprevisível e o runner
efêmero complica manter o SQLite.

**VPS ou homelab (D7):** o container só precisa de saída de rede — nada de
inbound. Homelab funciona sem IP fixo e ainda abre a opção de rodar Ollama
local e zerar o custo de LLM. Em qualquer um dos dois, montar `data/` em volume
e ter backup do `.db`.

---

## 7. Configuração (`.env`)

```bash
# Fontes
SOURCES_ENABLED=netvasco,supervasco
MAX_LOOKBACK_HOURS=8
USER_AGENT="VascoDigestBot/1.0 (+contato@exemplo.com)"

# LLM — Ollama Cloud
OLLAMA_HOST=https://ollama.com          # trocar por http://localhost:11434 no homelab
OLLAMA_API_KEY=
CLASSIFY_MODEL=gpt-oss:20b-cloud        # definido por benchmark (T-016b)
SUMMARIZE_MODEL=qwen3.5:397b            # definido por benchmark (T-016b)
CLASSIFY_CONFIDENCE_THRESHOLD=0.7
CLASSIFY_BATCH_SIZE=20
INCLUDE_INSTITUTIONAL=true              # D11 — institucional entra em `profissional`

# Bluesky
BLUESKY_ENABLED=true
BLUESKY_HANDLE=
BLUESKY_APP_PASSWORD=
BLUESKY_SESSION_PATH=/app/data/bsky_session.txt

# X
X_ENABLED=true                          # ⬅️ interruptor único (RF-07)
X_CLIENT_ID= ; X_CLIENT_SECRET= ; X_ACCESS_TOKEN= ; X_REFRESH_TOKEN=
X_IS_PREMIUM=true
X_LINK_POLICY=last_post                 # none | last_post | all_posts
X_MONTHLY_BUDGET_USD=                   # vazio = sem teto (D8)

# Operação
REQUIRE_APPROVAL=true
MAX_POSTS_PER_THREAD=4
DB_PATH=/app/data/vascobot.db
LOG_LEVEL=INFO
TZ=America/Sao_Paulo
```

---

## 8. Fases

| Fase | Entrega | Saída |
|---|---|---|
| **1. Núcleo** | Models, db, config, CLI, 2 adapters | `vascobot collect --dry-run` lista notícias reais |
| **2. Inteligência** | LLMProvider, regras, benchmark de modelo, dedup | **CA-02** atingido |
| **3. Saída** | Summarize, guardrails, compose, publishers | Posts corretos em dry-run |
| **4. Produção** | Docker, cron, aprovação, custo, logs | 7 execuções/dia por 1 semana |
| **5. Evolução** | Novas fontes, Dagster, Parquet/DuckDB | Opcional |

---

## 9. Estratégia de teste

- **Fixtures reais** em `tests/fixtures/`: RSS do NetVasco, HTML do SuperVasco,
  3 artigos de cada. Script `fetch_fixtures.py` para atualizar.
- **CSV rotulado** (`labeled_headlines.csv`, 100 manchetes) — teste de regressão
  do CA-02 **e** insumo do benchmark de modelos. Incluir obrigatoriamente:
  `Futsal Feminino Base:`, `Sub-16:`, `Sub-12:`, `Basquete:`, `Futmesa:`,
  `Natação Paralímpica:`, e ao menos 40 manchetes **sem prefixo** cobrindo
  jogos, mercado, SAF, torcida e história.
- **Publishers:** nunca chamados de verdade. `respx` para o X, fake para Bluesky.
- **LLM:** respostas gravadas em fixture. Sem rede no CI.
- **Custo:** dado um digest, asserir o custo estimado do X por `X_LINK_POLICY`.
- **Desacoplamento:** teste que roda o pipeline inteiro com `X_ENABLED=false`
  e verifica que nenhum draft de X foi gerado (CA-09).
