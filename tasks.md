# Tasks — Vasco Digest Bot

Ordenado por dependência. `[P]` = paralelizável com a anterior.
Cada tarefa tem *Definition of Done* verificável.

---

## Fase 1 — Fundação e coleta

### T-001 · Bootstrap
`pyproject.toml` (uv, Python 3.12), `src/vascobot/`, `.gitignore`,
`.env.example`, `README.md`, `ruff` + `mypy --strict` + `pytest`.
**DoD:** `uv sync && uv run ruff check . && uv run mypy src && uv run pytest` passa.

### T-002 · Config e logging
`config.py` com `pydantic-settings` (todas as variáveis do plan.md §7).
Validação na largada. `logging.py` com `structlog` JSON e processor que **redige
qualquer chave contendo** `key|token|password|secret`.
**DoD:** app falha se faltar `OLLAMA_API_KEY`; teste prova que segredo passado a
um log não aparece na saída (RNF-04 / CA-08).

### T-003 · Modelos de domínio [P]
`models.py`: `RawArticle`, `Article`, `Cluster`, `Digest`, `PostDraft`,
`PublishedPost`, `Category` (StrEnum), `Watermark`, `RunStats`.
Todo `datetime` **aware**; validator rejeita naive.
**DoD:** round-trip e rejeição de naive testados.

### T-004 · Fixtures reais [P]
Baixar para `tests/fixtures/`: RSS do NetVasco, HTML da listagem do SuperVasco,
3 artigos individuais de cada. Script `fetch_fixtures.py` para atualizar.
**DoD:** fixtures commitadas e reprodutíveis.

### T-005 · CSV rotulado de 100 manchetes [P]
`tests/fixtures/labeled_headlines.csv`. Obrigatório: `Futsal Feminino Base:`,
`Sub-16:`, `Sub-12:`, `Basquete:`, `Futmesa:`, `Natação Paralímpica:`, e
**≥ 40 manchetes sem prefixo** cobrindo jogos, mercado, SAF, torcida e história
(é aí que o LLM vai ser medido).
Alvo: ~45 profissional (incluindo ~12 institucionais — SAF, CEO, patrocínio, eleição),
~10 feminino, ~10 sub-20, ~8 sub-17, ~2 sub-15, ~25 descartado.
**DoD:** CSV completo, revisado, sem categoria vazia. **Este arquivo é o gate do projeto.**

### T-006 · Persistência
`db.py`: SQLite (WAL, FK ON), migrations versionadas em SQL puro, repositórios
tipados. Schema do plan.md §5.
**DoD:** migration roda do zero, idempotente; CRUD testado por tabela.

### T-007 · Interface SourceAdapter
`sources/base.py` (ABC), `sources/registry.py`, rate limiter por domínio,
cliente httpx compartilhado com User-Agent, timeout, retry, `robots.txt`.
**DoD:** adapter fake registrado é descoberto e executado pelo registry.

### T-008 · Adapter NetVasco
RSS `/news/rss.xml`. `external_id` de `/n/{id}/{slug}`. Data com fuso correto.
**DoD:** contra a fixture, ≥ 20 `RawArticle` com título, URL, `external_id` e
`published_at` aware corretos.

### T-009 · Adapter SuperVasco [P]
Scraping de `/ultimas-noticias-vasco/` com `selectolax`. `external_id` de
`-{id}.html`. **Atenção:** o horário vem `HH:MM` sem data — a data vem do
cabeçalho do grupo do dia. Paginar `?page=N` até passar o watermark. Ignorar
itens cuja URL sai do domínio (há links para `crvascodagama.com`).
**DoD:** contra a fixture, ≥ 40 artigos com `published_at` correto, **inclusive
na virada de dia**.

### T-010 · Normalização e hidratação
`pipeline/normalize.py`: canonicalização de URL (remover `utm_*`, `?q=`,
fragmento, normalizar `www.`), `content_hash`, corpo via `trafilatura` com
fallback para o lide.
**DoD:** duas URLs do mesmo artigo com querystrings diferentes → mesmo `id`.

### T-011 · Coleta + watermark
`pipeline/collect.py`: lê `source_state`, aplica watermark duplo (ID primário,
timestamp secundário), roda adapters com
`asyncio.gather(return_exceptions=True)`, avança watermark só em sucesso,
respeita `MAX_LOOKBACK_HOURS`.
**DoD:** **CA-06** — com uma fonte lançando exceção, a outra completa e o
watermark da que falhou não avança.

### T-012 · CLI base
`typer`: `vascobot run [--dry-run] [--since] [--sources]`,
`vascobot sources check`, `vascobot db migrate`.
**DoD:** `vascobot sources check` bate nas 2 fontes reais e imprime status.

---

## Fase 2 — Inteligência

### T-013 · Interface LLMProvider
`llm/base.py` (ABC `structured()`), `llm/schemas.py` (Pydantic dos contratos de
saída).
**DoD:** provider fake implementa a interface e é usado nos testes.

### T-014 · OllamaCloudProvider
`llm/ollama_cloud.py`: `format=Schema.model_json_schema()` (schema validado na
decodificação — research.md §4.2), schema **também no prompt**, `temperature=0`,
retry 3× com backoff, timeout, batch configurável.
**DoD:** contra fixture de resposta, devolve modelo Pydantic validado; erro de
rede vira exceção tipada, não crash.

### T-015 · Regras de classificação
`pipeline/rules.py`: camada 0 (exclusão, inclui `sub-14` e menores) e camada 1
(positiva, com Sub-16 → `base_sub17`). Regexes compiladas, insensíveis a caixa e
acento.
**DoD:** contra o CSV, **zero** falso-positivo em `descartado` — em especial
`Futsal Feminino Base:` **não** vira `feminino`.

### T-016 · Classificador LLM
`pipeline/classify.py` + `prompts/classify.md`. Batch de até 20 manchetes.
Recebe título + lide + editoria + URL. Respeita `INCLUDE_INSTITUTIONAL` (D11).
Camada 0 nunca chega ao LLM.
**DoD:** classifica corretamente contra fixture; confiança < limiar →
`pending_review`; com `INCLUDE_INSTITUTIONAL=true`, manchete sobre SAF/CEO cai
em `profissional` e nota de torcida organizada segue em `descartado`.

### T-016b · 📊 Benchmark de modelos do Ollama Cloud
Rodar contra o CSV do T-005:
- **Classificação:** `gpt-oss:20b-cloud` vs `qwen3.5`
- **Sumarização:** `qwen3.5:397b` vs `deepseek-v4-flash` vs `glm-5.1`
Medir acurácia, latência, consumo de cota e aderência ao schema.
Registrar a tabela de resultados **em `research.md` §4.4**.
**DoD:** `CLASSIFY_MODEL` e `SUMMARIZE_MODEL` escolhidos com número, não palpite.

### T-017 · Pipeline de classificação completo
Encadear camadas 0 → 1 → 2; gravar `category`, `confidence`, `classify_method`,
`llm_model`, `status`.
**DoD:** ⛔ **CA-02** — ≥ 90% de acurácia geral e ≥ 95% em `descartado`.
**Barreira de regressão do projeto.**

### T-018 · Degradação do LLM
Implementar RF-11: LLM indisponível → run `partial`, artigos não classificados
em `pending_review`, watermark **não avança** para eles, nada publicado.
**DoD:** **CA-10** — com provider fake lançando erro, o teste prova que nada foi
publicado e que a próxima execução reprocessa os pendentes.

### T-019 · Deduplicação
`pipeline/dedupe.py`: normalização de título, `token_set_ratio >= 85`,
ancoragem por entidade (≥ 1 token capitalizado em comum), clustering guloso
dentro da categoria, canônico = mais antigo.
**DoD:** **CA-03** — par real NetVasco/SuperVasco agrupa; teste negativo
"Vasco vence o Bahia" vs "Vasco vence o Santos" **não** agrupa.

---

## Fase 3 — Resumo e publicação

### T-019b · Priorização de clusters (RF-13)
`pipeline/priority.py`: peso determinístico por palavra-chave — 1 jogo/elenco/
lesão/suspensão, 2 mercado confirmado/comissão técnica, 3 mercado especulado,
4 institucional. Empate → mais recente. Ordenar antes do corte por
`MAX_POSTS_PER_THREAD`.
**DoD:** com 6 clusters em `profissional` (5 institucionais + 1 resultado de
jogo), o resultado do jogo **sempre** entra nos bullets. Sem chamada de LLM.

### T-020 · Sumarizador
`pipeline/summarize.py` + `prompts/summarize.md`, structured output
`ResumoCategoria`. Uma chamada por categoria.
**DoD:** headline ≤ 80 chars, bullets ≤ 140 chars, máx. 2; material insuficiente
→ `bullets: []`.

### T-021 · Guardrails
`pipeline/guardrails.py`: rejeita bullet com ≥ 10 palavras consecutivas
idênticas ao corpo-fonte; rejeita nome próprio ausente do cluster; rejeita
estouro de limite. Rejeição → `pending_review`.
**DoD:** resumo com jogador inexistente é rejeitado; cópia literal é rejeitada.

### T-022 · Registry de publishers + desacoplamento
`publishers/base.py` (ABC) e `publishers/registry.py` montado **a partir da
config**. O pipeline itera sobre ativos e nunca cita "X" por nome.
**DoD:** **CA-09** — pipeline roda com `X_ENABLED=false` sem erro e **sem gerar
nenhum draft de X**.

### T-023 · Composição em thread
`pipeline/compose.py`: grapheme count no Bluesky (`regex` `\X`), weighted count
no X (URL = 23), `MAX_POSTS_PER_THREAD`, `X_LINK_POLICY`
(`none`/`last_post`/`all_posts`), `idempotency_key` determinística.
**DoD:** **CA-04** — property test com emoji e acentos garante que nenhum draft
estoura o limite; teste cobre as 3 políticas de link.

### T-024 · Calculadora de custo do X
`publishers/cost.py`: tarifa por post detectando URL (research.md §3). A cada
run, logar gasto do run + acumulado do mês + **projeção mensal**.
**DoD:** custo de post com e sem link contabilizado corretamente; projeção
aparece no log de resumo do run. É o insumo para decidir D8.

### T-025 · Publisher Bluesky
`publishers/bluesky.py` com `atproto`. **Sessão persistida e reaproveitada**
(`export_session_string` / `login(session_string=...)`) — limite de 30
`createSession`/5min. Facets via `TextBuilder`. Thread com refs `root` e `parent`.
**DoD:** thread de 4 posts com refs corretas; teste prova reuso da sessão em disco.

### T-026 · Publisher X + budget guard [P]
`publishers/x.py`, OAuth 2.0 user context. Se `X_MONTHLY_BUDGET_USD` estiver
definido e estourado → `skipped` + alerta, **sem exceção**. Vazio → só registra.
**DoD:** com orçamento estourado, não chama a API e marca `skipped`; Bluesky
segue normalmente.

### T-027 · Idempotência
`idempotency_key` UNIQUE; conflito → `skipped`.
**DoD:** **CA-05** — rodar a mesma janela duas vezes não gera post novo.

---

## Fase 4 — Produção

### T-028 · Fila de aprovação
`REQUIRE_APPROVAL=true` → posts nascem `pending`.
`vascobot approve [--run-id] [--category]` mostra os drafts e libera;
`vascobot reject`.
**DoD:** RF-10 — nada publicado sem aprovação com a flag ligada.

### T-029 · Pipeline `run` fim-a-fim
Encadeia as 7 etapas, grava `runs.stats_json` (coletados, descartados por
camada, clusters, digests, posts por plataforma, custo do X, projeção mensal,
duração por etapa), status `ok|partial|failed`.
**DoD:** **CA-01** e **RNF-01** — execução real < 3 min.

### T-030 · Docker + cron
`Dockerfile` multi-stage non-root, `docker-compose.yml` com volume em `data/`,
`crontab` com `TZ=America/Sao_Paulo` e `0 0,6,9,12,15,18,21 * * *`.
Documentar as duas variantes de deploy (VPS e homelab) — D7 ainda aberto.
**DoD:** **CA-07** — container sobe, cron dispara, e artigo publicado às 02:00
BRT aparece no digest das 06:00.

### T-031 · Observabilidade
Resumo de run em JSON + `vascobot stats --days 7`. Alerta (log ERROR) quando:
fonte falha 3 runs seguidos, taxa de fallback para LLM > 70%, gasto do X > 80%
do teto (se houver), ou taxa de `pending_review` > 20%.
**DoD:** `vascobot stats` imprime tabela por dia e por categoria.

### T-032 · Documentação
`README.md`: setup, credenciais (Bluesky App Password, X OAuth, Ollama API key),
como adicionar fonte, dry-run, aprovação, **como desligar o X** e a **tabela de
custo com o aviso sobre links**.
**DoD:** um terceiro sobe do zero seguindo só o README.

### T-033 · Soft launch (2 semanas)
Rodar com `REQUIRE_APPROVAL=true`, revisando cada digest. Anotar erros de
classificação e realimentar o CSV do T-005. **Decidir D8** (teto do X) com o
custo medido pelo T-024. **Avaliar** se `profissional` merece
`MAX_POSTS_PER_THREAD=5` próprio.
**DoD:** 14 dias sem erro factual grave; custo mensal real conhecido; só então
avaliar desligar a aprovação.

---

## Fase 5 — Evolução (opcional)

- **T-034** Novas fontes: `crvascodagama.com`, `vasco.com.br`
- **T-035** Ollama local no homelab (`OLLAMA_HOST=http://localhost:11434`) → custo de LLM zero
- **T-036** Migrar agendamento para Dagster (`@op` chamando `run()`, partição horária, backfill, sensor por fonte)
- **T-037** Export Parquet + análise histórica em DuckDB
- **T-038** Feed próprio por categoria (RSS/Telegram)
- **T-039** Reavaliar ge.globo, se fizer falta

---

## Ordem de execução

```
T-001 → T-002 → T-003 [P] → T-004 [P] → T-005 [P] → T-006
      → T-007 → T-008 → T-009 [P] → T-010 → T-011 → T-012
      → T-013 → T-014 → T-015 → T-016 → T-016b → T-017 ⛔ → T-018 → T-019 → T-019b
      → T-020 → T-021 → T-022 → T-023 → T-024 → T-025 [P] → T-026 [P] → T-027
      → T-028 → T-029 → T-030 → T-031 → T-032 → T-033
```

⛔ **Gate em T-017.** Não avançar para a Fase 3 sem CA-02 verde. Se a
classificação erra, tudo depois publica lixo com fluência.
