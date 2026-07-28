# Vasco Digest Bot

Digest automatizado das notícias do Club de Regatas Vasco da Gama, publicado em
**thread no Bluesky e no X**, 7×/dia, **separado por categoria**.

Coleta NetVasco (RSS) e SuperVasco (scraping), classifica em 3 camadas
(regra → regra → LLM), deduplica cross-fonte, resume por categoria com guardrails
anti-alucinação e publica de forma independente por plataforma.

Contexto de engenharia: `spec.md` · `plan.md` · `research.md` · `tasks.md` · `CLAUDE.md`.

---

## Sumário

- [Setup rápido](#setup-rápido)
- [Credenciais](#credenciais)
- [Uso](#uso)
- [Aprovação manual](#aprovação-manual)
- [Como desligar o X](#como-desligar-o-x)
- [Custo do X — aviso sobre links](#custo-do-x--aviso-sobre-links)
- [Adicionar uma fonte](#adicionar-uma-fonte)
- [Deploy (Docker + cron)](#deploy-docker--cron)
- [Desenvolvimento](#desenvolvimento)

---

## Setup rápido

Requer **Python 3.12+** e [`uv`](https://docs.astral.sh/uv/).

```bash
make setup            # uv sync + pre-commit
cp .env.example .env  # preencha as credenciais (ver abaixo)
uv run vascobot db migrate
uv run vascobot run --dry-run   # gera tudo sem publicar
```

---

## Credenciais

Todas via `.env` (nunca commitado — `.gitignore` + gitleaks). Mínimo para rodar:

### Ollama Cloud (LLM)

1. Crie conta em [ollama.com](https://ollama.com) e gere uma API key.
2. `OLLAMA_API_KEY=sk-...`
3. `CLASSIFY_MODEL` já vem definido (`deepseek-v4-flash`, escolhido por benchmark —
   ver `research.md` §4.4). Para rodar LLM local (custo zero), troque
   `OLLAMA_HOST=http://localhost:11434`.

### Bluesky

1. Crie uma conta **dedicada** para o bot.
2. Em *Settings → App Passwords*, gere uma senha no formato `xxxx-xxxx-xxxx-xxxx`.
3. `BLUESKY_HANDLE=seubot.bsky.social` e `BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx`.

> A sessão é persistida em `BLUESKY_SESSION_PATH` e reaproveitada — o limite é
> de 30 `createSession`/5min por handle. Não apague esse arquivo à toa.

### X (opcional — ver [como desligar](#como-desligar-o-x))

OAuth 2.0 user context. No developer portal do X, crie um app e obtenha:
`X_CLIENT_ID`, `X_CLIENT_SECRET`, `X_ACCESS_TOKEN`, `X_REFRESH_TOKEN`.

> ⚠️ O X **cobra por post desde fev/2026**. Leia a [seção de custo](#custo-do-x--aviso-sobre-links)
> antes de habilitar.

---

## Uso

```bash
uv run vascobot sources check        # lista as fontes registradas
uv run vascobot db migrate           # cria/atualiza o SQLite (idempotente)
uv run vascobot run --dry-run        # pipeline inteiro, sem publicar
uv run vascobot run                  # execução real
uv run vascobot stats --days 7       # tabela por dia + alertas
```

Flags do `run`:

| Flag | Efeito |
|---|---|
| `--dry-run` | Gera digests e drafts, **não publica** |
| `--sources netvasco` | Roda só as fontes indicadas (CSV) |
| `--offline` | Smoke test, não toca rede |

---

## Aprovação manual

Com `REQUIRE_APPROVAL=true` (**padrão nas 2 primeiras semanas**, RF-10), os posts
nascem `pending` e **nada é publicado** sem liberação:

```bash
uv run vascobot run                          # gera drafts pending
uv run vascobot approve --run-id <run>       # revisa e libera
uv run vascobot approve --run-id <run> --category profissional  # só uma categoria
uv run vascobot reject  --run-id <run>       # descarta (marca skipped)
```

O `run-id` aparece no JSON de saída do `run`.

---

## Como desligar o X

Interruptor único (RF-07). No `.env`:

```bash
X_ENABLED=false
```

Com isso o X é removido do pipeline **inteiro** — inclusive da composição, sem
gerar nenhum draft de X e sem afetar o Bluesky. Basta reiniciar o container.

Segundo interruptor, automático: se `X_MONTHLY_BUDGET_USD` estiver definido e for
estourado, o publisher do X marca os posts como `skipped` e alerta — sem exceção,
sem afetar o Bluesky.

---

## Custo do X — aviso sobre links

Desde fev/2026 o X cobra por post (research.md §3). **Post com URL custa ~13× mais**:

| Operação | Custo aprox. |
|---|---|
| Post **sem link** | US$ 0,015 |
| Post **com URL** | **US$ 0,20** |

Projeção mensal (~17 threads/dia × 4 posts), por política de link:

| `X_LINK_POLICY` | Custo/mês |
|---|---|
| `all_posts` | ~US$ 420 ❌ |
| `last_post` (padrão) | ~US$ 128 ⚠️ |
| `none` | ~US$ 32 |

> **Recomendação:** `X_LINK_POLICY=last_post` — preserva o link (a thread termina
> com "fontes: …") e corta ~70% do custo. A cada run o bot loga o gasto e a
> projeção mensal; use `vascobot stats` para acompanhar.

Bluesky é **gratuito** e sempre carrega os links via facets.

---

## Adicionar uma fonte

1. Crie `src/vascobot/sources/minhafonte.py` com uma classe que herda de
   `SourceAdapter` e implementa `async def discover(self, since: Watermark)`.
2. Registre-a em `_default_registry()` (`cli.py`) e adicione o `source_id` em
   `SOURCES_ENABLED` no `.env`.
3. Escreva um teste de contrato contra uma fixture real em `tests/fixtures/`.

O pipeline (coleta → classificação → publicação) **não muda** — a arquitetura é
plugável nas bordas.

---

## Deploy (Docker + cron)

O container agenda `vascobot run` na grade `0,6,9,12,15,18,21h` (America/Sao_Paulo).
O vão de 6h entre 00h e 06h é coberto por `MAX_LOOKBACK_HOURS=8` (CA-07).

```bash
docker compose build
docker compose up -d
docker compose logs -f
```

O estado (`data/vascobot.db`, sessão do Bluesky) fica num volume — faça backup dele.

Duas variantes de hospedagem (D7, em aberto):

- **VPS:** container só precisa de saída de rede, nada de inbound.
- **Homelab:** funciona sem IP fixo e abre a opção de rodar Ollama local
  (`OLLAMA_HOST=http://localhost:11434`), zerando o custo de LLM.

---

## Desenvolvimento

```bash
make fmt      # ruff format + fix
make lint     # ruff sem fix
make types    # mypy --strict
make test     # unit + contract (rápido, sem rede)
make cov      # cobertura com limiares
make accept   # só os critérios de aceite CA-xx
make check    # ⬅️ portão completo — verde = pronto
make integration  # testes que tocam rede real (manual, nunca no CI)
```

Regras de engenharia em `CLAUDE.md`. Resumo: TDD obrigatório, zero rede em teste,
segredo nunca no repositório, `make check` verde é a definição de "terminei".

### Estrutura

```
src/vascobot/
├── cli.py · config.py · models.py · db.py · repo.py · logging.py · observability.py
├── sources/       base · registry · netvasco · supervasco
├── llm/           base · ollama_cloud · fake · schemas
├── pipeline/      collect · normalize · rules · classify · classify_pipeline
│                  degrade · dedupe · priority · summarize · guardrails
│                  compose · idempotency · run
├── publishers/    base · registry · bluesky · x · cost
└── prompts/       classify.md · summarize.md
```

---

## Segurança

Segredos só via `.env`. Nunca commitar `.env`, `data/*.db`, `bsky_session.txt`.
`gitleaks` roda no pre-commit e no CI. O bot lê portais de notícia mas **nunca
reproduz texto literal** — o guardrail rejeita bullet com ≥ 10 palavras
consecutivas iguais à fonte (RNF-07).
