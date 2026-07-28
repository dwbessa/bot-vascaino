# Vasco Digest Bot

Digest automatizado das notícias do Club de Regatas Vasco da Gama, publicado em
thread no Bluesky e no X, 7×/dia, separado por categoria.

Contexto: `spec.md` · `plan.md` · `research.md` · `tasks.md` · `CLAUDE.md`.

---

## Setup

Requer Python 3.12+ e [`uv`](https://docs.astral.sh/uv/).

```bash
make setup            # uv sync + pre-commit
cp .env.example .env  # preencha credenciais
make check            # portão completo (lint + types + cov + aceite)
```

## Uso

```bash
uv run vascobot sources check    # ping nas fontes
uv run vascobot db migrate       # cria SQLite
uv run vascobot run --dry-run    # roda pipeline sem publicar
```

## Comandos de desenvolvimento

Ver `Makefile`. `make check` verde é a definição de "terminei".

## Segurança

Segredos só via `.env`. Nunca commitar `.env`, `data/*.db`, nem `bsky_session.txt`.
`gitleaks` no pre-commit e no CI barra vazamento.

## Estrutura

```
src/vascobot/
├── cli.py · config.py · models.py · db.py · logging.py
├── sources/       netvasco.py · supervasco.py
├── llm/           ollama_cloud.py
├── pipeline/      collect · normalize · rules · classify · dedupe
│                  priority · summarize · guardrails · compose
├── publishers/    bluesky.py · x.py · cost.py
└── prompts/       classify.md · summarize.md
```
