# CLAUDE.md

Regras de engenharia deste repositório. **Leia antes de escrever qualquer linha.**

Contexto funcional: `specs/001-vasco-digest/`
— `spec.md` (o quê) · `plan.md` (como) · `research.md` (fatos verificados) · `tasks.md` (backlog)

---

## 0. Regras inegociáveis

Estas quatro valem mais que qualquer instrução de tarefa. Se uma tarefa parecer
exigir violá-las, **pare e pergunte**.

1. **Teste primeiro.** Nenhum código de produção é escrito sem um teste que
   falhe antes. Ver §2.
2. **Não enfraqueça o portão para passar.** É proibido baixar limiar de
   cobertura, adicionar `# type: ignore` sem código e justificativa, marcar
   teste como `xfail`/`skip` para ficar verde, afrouxar regra do ruff, ou
   comentar assert. Se o portão está fechado, o problema é o código.
3. **Zero rede em teste.** Nenhum teste do CI toca a internet, o Ollama Cloud,
   o X ou o Bluesky. Fixtures e fakes. Ver §4.
4. **Segredo nunca entra no repositório.** Nem em fixture, nem em log, nem em
   docstring, nem "temporariamente". Ver §6.

---

## 1. Comandos

```bash
make setup       # uv sync + pre-commit install
make fmt         # ruff format + ruff check --fix
make lint        # ruff check (sem fix)
make types       # mypy --strict src
make test        # pytest unit + contract (rápido, sem rede)
make cov         # pytest com cobertura e limiares
make accept      # somente os testes de aceite (CA-xx)
make check       # lint + types + cov + accept   ⬅️ rode ANTES de dizer "pronto"
make integration # testes que tocam rede real — manual, nunca no CI
```

**`make check` verde é a definição de "terminei".** Não anuncie conclusão de
tarefa sem ter rodado e visto passar.

---

## 2. TDD — o ciclo obrigatório

Para cada tarefa do `tasks.md`:

```
1. RED     Escreva o teste que expressa o DoD da tarefa. Rode. Veja falhar
           pelo motivo certo (não por ImportError ou typo).
2. GREEN   Escreva o mínimo de código para passar. Feio é aceitável aqui.
3. REFACTOR Limpe com os testes verdes. Nenhum comportamento novo.
4. GATE    make check
```

Regras de disciplina:

- **Um teste falhando por vez.** Não escreva cinco testes e depois o código.
- **Se você escreveu código antes do teste, apague o código** e recomece.
  Escrever o teste depois quase sempre produz um teste que só descreve o que o
  código já faz.
- **O teste vem do DoD**, não da implementação. Abra o `tasks.md`, leia o DoD,
  traduza em asserção.
- **Bug encontrado = teste de regressão primeiro.** Reproduza o bug num teste
  que falha, só então corrija.

### O que não precisa de TDD

Migrations SQL, `Dockerfile`, `crontab`, `.env.example`, docstrings. Use bom
senso: se não tem lógica, não tem teste unitário.

---

## 3. Rastreabilidade dos critérios de aceite

Cada `CA-xx` do `spec.md` §6 tem **um teste com nome correspondente**, marcado
`@pytest.mark.acceptance`. Isso é o que garante que o software "sempre se sai
bem nos critérios técnicos" — o CI reprova se algum sumir.

| CA | Teste | Arquivo |
|---|---|---|
| CA-01 | `test_ca01_collects_since_watermark` | `tests/acceptance/test_ca01_collect.py` |
| CA-02 | `test_ca02_classification_accuracy` | `tests/acceptance/test_ca02_classify.py` |
| CA-03 | `test_ca03_cross_source_dedup` | `tests/acceptance/test_ca03_dedupe.py` |
| CA-04 | `test_ca04_post_length_limits` | `tests/acceptance/test_ca04_compose.py` |
| CA-05 | `test_ca05_idempotent_rerun` | `tests/acceptance/test_ca05_idempotency.py` |
| CA-06 | `test_ca06_source_failure_isolated` | `tests/acceptance/test_ca06_resilience.py` |
| CA-07 | `test_ca07_overnight_window_covered` | `tests/acceptance/test_ca07_window.py` |
| CA-08 | `test_ca08_no_secrets_in_logs` | `tests/acceptance/test_ca08_secrets.py` |
| CA-09 | `test_ca09_x_fully_decoupled` | `tests/acceptance/test_ca09_decoupling.py` |
| CA-10 | `test_ca10_llm_outage_degrades_safely` | `tests/acceptance/test_ca10_llm_outage.py` |

`tests/acceptance/test_traceability.py` varre o `spec.md`, extrai os `CA-xx` e
falha se algum não tiver teste correspondente. **Adicionou CA no spec? O CI
reprova até existir o teste.**

### Gate especial — CA-02

`T-017` é a barreira do projeto. O teste roda `labeled_headlines.csv` inteiro e
exige **≥ 90% de acurácia geral e ≥ 95% de precisão em `descartado`**. Se
reprovar, **não avance para a Fase 3** — pipeline com classificação ruim publica
lixo com fluência. Não relaxe esses números para destravar; melhore as regras ou
troque o modelo (T-016b).

---

## 4. Estratégia de teste

### Camadas e marcadores

| Marcador | O que é | Rede? | CI? |
|---|---|---|---|
| *(sem marcador)* | Unitário, lógica pura, < 10ms | ❌ | ✅ |
| `@pytest.mark.contract` | Parsing contra fixtures reais em disco | ❌ | ✅ |
| `@pytest.mark.acceptance` | Um CA-xx do spec | ❌ | ✅ |
| `@pytest.mark.integration` | Toca API real | ✅ | ❌ manual |

`pytest.ini` configura `addopts = -m "not integration"`. Rede real só via
`make integration`, rodado por humano.

### Fakes obrigatórios

- **LLM:** `FakeLLMProvider` devolvendo fixtures gravadas. Nunca chame Ollama
  Cloud em teste automatizado.
- **Bluesky:** `FakeBlueskyClient`. Nunca instancie `atproto.Client` real.
- **X:** `respx` interceptando httpx. Nunca faça POST real.
- **Relógio:** `freezegun` ou injeção de `now()`. Nada de `datetime.now()`
  solto — o ruff bloqueia via regra `DTZ`.

### Cobertura

| Alvo | Mínimo |
|---|---|
| Global | **85%** |
| `pipeline/rules.py`, `pipeline/priority.py`, `pipeline/compose.py`, `publishers/cost.py` | **100%** |

São lógica pura e determinística, onde erro é silencioso e caro. Sem desculpa
para não cobrir. Cobertura é piso, não meta — 100% de cobertura com asserção
fraca não vale nada.

---

## 5. Ferramental e portões estáticos

| Ferramenta | Papel | Configuração |
|---|---|---|
| `uv` | Deps e venv | `pyproject.toml` |
| `ruff` | Lint + format | `pyproject.toml` |
| `mypy --strict` | Tipos | `pyproject.toml` |
| `pytest` + `pytest-cov` | Testes | `pyproject.toml` |
| `pre-commit` | Portão local | `.pre-commit-config.yaml` |
| `gitleaks` | Segredos | `.gitleaks.toml` |
| GitHub Actions | Portão remoto | `.github/workflows/ci.yml` |

**O CI roda exatamente o mesmo `make check` do local.** Se passa aqui e quebra
lá, o bug é na paridade, e ela é prioridade de correção.

### Regras do ruff que importam aqui

- `DTZ` — proíbe `datetime` naive. Todo timestamp deste projeto é
  timezone-aware (America/Sao_Paulo). Regra, não convenção.
- `S` (bandit) — pega segredo hardcoded, `assert` em produção, `subprocess` inseguro.
- `T20` — proíbe `print()`. Use `structlog`.
- `ERA` — proíbe código comentado. Git é o histórico.
- `PTH` — `pathlib` em vez de `os.path`.
- `ASYNC` — pega chamada bloqueante dentro de corrotina.

### Supressões

Permitidas apenas com **código específico + justificativa na mesma linha**:

```python
result = legacy_call()  # type: ignore[no-any-return]  # lib sem stubs, issue #12
value = eval(expr)  # noqa: S307  # expr vem de constante interna, nunca de input
```

Proibido: `# type: ignore` pelado, `# noqa` pelado, `--no-verify` no commit.

---

## 6. Segurança e segredos

### Nunca commitados

`.env` · `data/*.db` · `data/bsky_session.txt` · qualquer token, chave ou
App Password. Todos no `.gitignore` **e** cobertos pelo gitleaks.

### gitleaks

Roda em pre-commit (staged) e no CI (histórico completo). `.gitleaks.toml` tem
regras próprias para os segredos deste projeto:

- App Password do Bluesky (`xxxx-xxxx-xxxx-xxxx`)
- `OLLAMA_API_KEY`, `X_CLIENT_SECRET`, `X_ACCESS_TOKEN`, `X_REFRESH_TOKEN`
  com valor não-vazio

Alarme falso? Corrija o `.gitleaks.toml` com allowlist **estreita** e explique
no commit. Nunca desligue a ferramenta.

### Log

O processor de redação do `structlog` (T-002) apaga qualquer chave contendo
`key|token|password|secret`. **CA-08 testa isso.** Ao adicionar um segredo novo
à config, confirme que o nome bate com o padrão — senão, estenda o padrão junto.

### Conteúdo de terceiros (RNF-07)

Este bot lê portais de notícia. **Nunca reproduza texto literal.** O guardrail
do T-021 rejeita bullet com ≥ 10 palavras consecutivas iguais à fonte. Não
enfraqueça esse número: é proteção jurídica, não estilo.

---

## 7. Convenções de código

- **Python 3.12.** `match`, `StrEnum`, tipos nativos (`list[str]`, `X | None`).
- **Pydantic v2** nas fronteiras (config, contrato entre etapas, saída de LLM).
  Dataclass ou tipo nativo no miolo.
- **Async** só onde há I/O concorrente (coleta, publicação). Lógica pura é síncrona.
- **Sem ORM.** SQL cru em `db.py`, sempre parametrizado. Nada de f-string em query.
- **Toda etapa do pipeline é uma função com entrada e saída explícitas.** Nada
  de I/O escondido no meio da lógica — é o que torna o teste barato.
- **Nomes de domínio em português** (`categoria`, `resumo`, `manchete`) quando
  são conceito do negócio; inglês no resto. Consistência dentro do módulo importa
  mais que a escolha.

### Erros

Exceções tipadas por domínio (`SourceError`, `LLMUnavailableError`,
`PublishError`). Nunca `except Exception: pass`. Nunca engula erro sem log.

---

## 8. Git

```
feat(sources): adapter do SuperVasco com paginação
fix(compose): contagem por grapheme no Bluesky
test(classify): cobre Futsal Feminino Base na camada 0
chore(deps): bump ruff
docs(spec): decisão D11 sobre pauta institucional
```

- Branch: `feat/T-009-supervasco-adapter` (prefixo do ID da tarefa).
- **Um commit por ciclo TDD completo** (red → green → refactor), não por arquivo.
- `--no-verify` é proibido.
- PR só com `make check` verde e o DoD da tarefa citado na descrição.

---

## 9. Checklist antes de dizer "pronto"

```
[ ] Existe teste que falhava antes e passa agora
[ ] O teste veio do DoD do tasks.md, não da implementação
[ ] make check verde (lint + types + cobertura + aceite)
[ ] Nenhum # type: ignore ou # noqa novo sem código e justificativa
[ ] Nenhum segredo, .env ou .db no diff
[ ] Se mexeu em classificação → CA-02 ainda ≥ 90% / ≥ 95%
[ ] Se mexeu em spec.md → os CA-xx afetados têm teste
[ ] Se mudou comportamento → docs/spec atualizados no mesmo commit
```

---

## 10. Armadilhas específicas deste projeto

Erros que já sabemos que vão acontecer. Cada um tem teste obrigatório.

| Armadilha | Por quê | Teste |
|---|---|---|
| `Futsal Feminino Base:` classificado como `feminino` | Contém "Feminino"; a camada 0 tem que matar antes | `test_rules.py` |
| `published_at` errado no SuperVasco | Horário vem `HH:MM` sem data; a data vem do cabeçalho do dia | `test_sources_supervasco.py` — cobrir virada de dia |
| Notícia das 02:00 sumindo | Vão de 6h entre 00h e 06h na grade | CA-07 |
| Login novo no Bluesky a cada run | Limite de 30 `createSession`/5min | `test_bluesky.py` |
| Custo do X estourando | Post com URL custa ~13× mais | `test_cost.py` nas 3 políticas |
| Institucional expulsando o resultado do jogo | `profissional` virou a categoria dominante | RF-13 / `test_priority.py` |
| `len()` em vez de graphemes | Emoji e acento quebram a conta | CA-04, property test |
| Watermark avançando após falha | Perde notícia silenciosamente | CA-06 |
