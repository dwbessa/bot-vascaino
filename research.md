# Research — Vasco Digest Bot

Descobertas verificadas em 2026-07-27.

---

## 1. Fontes de notícia

### 1.1 NetVasco — `netvasco.com.br`

- ✅ **RSS confirmado:** `https://www.netvasco.com.br/news/rss.xml` (responde `application/xml`).
- URLs: `https://www.netvasco.com.br/n/{id}/{slug}` — **ID numérico sequencial**
  (386872, 386869...). Serve como watermark natural, imune a fuso.
- Home tem lista cronológica `HH:MM` agrupada por dia — fallback se o `pubDate` falhar.

**Taxonomia real de prefixos observada:**

```
Sub-20:                    → base_sub20
Sub-17:                    → base_sub17
Sub-16:                    → base_sub17   (decisão do usuário)
Feminino:                  → feminino
Futsal Base:               → descartado
Futsal Feminino Base:      → descartado  ⚠️ contém "Feminino"
E-Sports:                  → descartado
Natação Paralímpica:       → descartado
(sem prefixo)              → ~60% do volume, vai obrigatoriamente para o LLM
```

### 1.2 SuperVasco — `supervasco.com`

- ❌ **Sem RSS.** CMS próprio ("Desenvolvido por Sile"). Scraping da listagem.
- Listagem: `https://www.supervasco.com/ultimas-noticias-vasco/` com `?page=N`.
- URLs: `.../noticias/{slug}-{id}.html` — **ID sequencial** (451844, 451843...).
- Editorias navegáveis (sinal forte de classificação):
  `/editoria/categorias-de-base/`, `/futebol/`, `/clube/`, `/mercado/`,
  `/outros-esportes/`, `/imprensa/`, `/politica/`, `/torcida/`, `/site/`
- Prefixos: `Feminino:`, `Sub-17:`, `Sub-20:`, `Basquete:`, `Futmesa:`
- ⚠️ **Republica conteúdo de terceiros:** alguns itens apontam para
  `crvascodagama.com`; cita NetVasco como fonte (`NTV: ...`). Confirma o RF-04.

### 1.3 ge.globo — ❌ REMOVIDO DO ESCOPO

Retirado por decisão do usuário em 2026-07-27. Motivos que corroboram: SPA sem
RSS confirmado, maior probabilidade de bloqueio a crawler, e cobertura
redundante — NetVasco e SuperVasco já cobrem base e feminino com mais volume.

Se um dia voltar, o padrão legado a testar primeiro é
`.../servico/semantica/editorias/plantao/futebol/times/{time}/feed.rss`.

### 1.4 Observação sobre volume

Nas duas fontes restantes, o profissional masculino é o carro-chefe e **quase
nunca vem prefixado**. Feminino e base são minoria mas vêm bem sinalizados. Ou
seja: a regra determinística resolve as categorias pequenas, e o LLM carrega o
peso de decidir o que, dentro do bolo sem prefixo, é de fato futebol
profissional e o que é descarte.

---

## 2. Bluesky / AT Protocol

- SDK: `atproto` (MarshalX). Tipado, sync e async.
- Auth: handle + **App Password**.
- ⚠️ `createSession` limitado a **30/5min e 300/dia por handle**. Obrigatório
  **persistir e reaproveitar a sessão** entre execuções.
- 300 graphemes por post. Links precisam de *facets* (byte offsets) —
  usar `client_utils.TextBuilder()`, nunca concatenar string.
- Thread: cada reply precisa de refs **root** e **parent**.
- Custo zero.

---

## 3. X API — pay-per-use desde fevereiro/2026

Tier gratuito descontinuado para devs novos; Basic ($200) e Pro ($5.000) só para
assinantes legados.

| Operação | Custo |
|---|---|
| Post **sem link** | ~US$ 0,015 |
| Post **com URL** | **~US$ 0,20** (desde abril/2026) |
| Leitura de post | ~US$ 0,005 |

**X Premium (assinatura de consumidor) NÃO dá acesso à API.** São produtos
separados.

### Projeção com a decisão tomada (thread + links)

Premissa realista: ~2,5 categorias com notícia por execução × 7 execuções =
~17 threads/dia × 4 posts = ~70 posts/dia.

| `X_LINK_POLICY` | Cálculo | Custo/mês |
|---|---|---|
| `all_posts` | 70 × 0,20 × 30 | **US$ 420** ❌ |
| `last_post` (1 link por thread) | (17×0,20 + 53×0,015) × 30 | **US$ 128** ⚠️ |
| `none` | 70 × 0,015 × 30 | **US$ 32** |

> **Recomendação:** `X_LINK_POLICY=last_post`. Preserva o link (a thread termina
> com "fontes: ...") e corta 70% do custo em relação a link em todo post. O
> `last_post` pode agregar todas as URLs do digest num post só.

Como a decisão é reversível por variável de ambiente, dá para começar em
`last_post`, medir 7 dias reais e ajustar com número na mão.

*(Preço do X mudou duas vezes em quatro meses. Reconferir na documentação
oficial antes de fechar orçamento.)*

---

## 4. Ollama Cloud

### 4.1 Como funciona

Serviço gerenciado que roda modelos open-weight grandes na infra da Ollama.
Mesma superfície HTTP do runtime local — o código não muda entre local e cloud,
o que é ideal para o cenário homelab/VPS ainda indefinido.

- Auth: `OLLAMA_API_KEY`
- Dois endpoints: `/api/chat` (nativo) e `/v1/chat/completions` (OpenAI-compatível)
- SDK Python: `pip install ollama`

### 4.2 Structured outputs — o recurso decisivo aqui

O Ollama valida **JSON Schema durante a decodificação**, não depois. Integra
direto com Pydantic:

```python
from ollama import Client
from pydantic import BaseModel


class Classificacao(BaseModel):
    categoria: Literal[
        "profissional", "feminino", "base_sub20", "base_sub17", "base_sub15", "descartado"
    ]
    confianca: float
    motivo: str


resp = client.chat(
    model="qwen3.5:397b",
    messages=[...],
    format=Classificacao.model_json_schema(),
    options={"temperature": 0},
)
Classificacao.model_validate_json(resp.message.content)
```

Isso elimina o parse defensivo de ```json e a maior parte dos retries.
**Passar o schema também no prompt**, além do campo `format` — a documentação
recomenda, melhora a aderência.

### 4.3 Planos

| Plano | Preço | Modelos simultâneos | Cota |
|---|---|---|---|
| Free | US$ 0 | 1 | ~5M tokens/semana |
| Pro | US$ 20/mês | 3 | ~50× o Free |
| Max | US$ 100/mês | 10 | ~5× o Pro |

Cota medida em **tempo de GPU**, não em tokens fixos. Modelos têm "níveis de
uso" de 1 (leve, ex. `gpt-oss:20b`) a 4 (pesado, ex. `deepseek-v4-pro`).

**Estimativa deste projeto:** ~210 classificações/dia (batched) + ~35
sumarizações/dia ≈ 1M tokens/semana. **Cabe no Free**, mas o Pro (US$20) dá
folga e concorrência para rodar classificador e sumarizador em paralelo.

### 4.4 Modelos candidatos

Evitar os modelos *coder* (`qwen3-coder`, `deepseek-v4-pro`) — otimizados para
código, desperdício aqui.

| Tarefa | Candidatos | Racional |
|---|---|---|
| **Classificação** (manchete pt-BR → enum) | `gpt-oss:20b-cloud` (nível 1), `qwen3.5` | Tarefa curta e barata. Qwen tem reputação de melhor multilíngue; gpt-oss:20b consome menos cota. **Decidir por benchmark, não por intuição.** |
| **Sumarização** (pt-BR fluente, factual) | `qwen3.5:397b`, `deepseek-v4-flash`, `glm-5.1` | Precisa de fluência em pt-BR e baixa taxa de alucinação. Também por benchmark. |

O CSV rotulado de 100 manchetes (T-006) existe exatamente para transformar essa
escolha em medição. Ver tarefa T-016b.

#### Resultado do benchmark (T-016b, 2026-07-28)

Rodado contra `labeled_headlines.csv` (103 manchetes, incluindo as armadilhas
`Futsal Feminino Base:`, `Sub-16:`, `Sub-12:`, SAF/CEO/patrocínio, torcida
organizada e histórico), batch de 20, `INCLUDE_INSTITUTIONAL=true`,
`temperature=0`, structured output validado por schema.

| Modelo | Acurácia geral | Precisão em `descartado` | Latência p50/batch |
|---|---|---|---|
| `gpt-oss:20b` | 100.0% | 100.0% | 16173 ms |
| `qwen3.5:397b` | 100.0% | 100.0% | 56811 ms |
| **`deepseek-v4-flash`** ✅ | **100.0%** | **100.0%** | **6835 ms** |

**Decisão:** `CLASSIFY_MODEL=deepseek-v4-flash`. Empatou em qualidade com os
outros dois e é 2,4× mais rápido que o `gpt-oss:20b` e 8,3× mais rápido que o
`qwen3.5:397b`. Menor latência = menos risco de estourar `RNF-01` (< 3 min).

**Sobre a acurácia 100%:** o CSV foi escrito à mão a partir de padrões reais
dos portais. É a barra que o T-017 (CA-02) exige. Realimente com casos-limite
observados no soft launch (T-033) — a resiliência real é ganha lá.

**Sumarização (T-020):** benchmark de `SUMMARIZE_MODEL` fica pra Fase 3, quando
já houver material real (Digest fixture). Candidatos: `qwen3.5:397b`,
`glm-5.1`, `nemotron-3-super`.

### 4.5 ⚠️ Riscos operacionais

- **Sem SLA.** Serviço publicado "as is", sem garantia de uptime. Há registro de
  uma janela de ~95% de falha em abril/2026.
- **Mitigação obrigatória:** retry com backoff; se o LLM ficar indisponível,
  a execução **não** publica com classificação incompleta — grava o run como
  `partial` e deixa os artigos em `pending_review` para a próxima janela. O
  watermark **não avança** para os itens não classificados.
- Abstrair atrás de uma interface `LLMProvider` permite plugar Ollama local
  (custo zero, se o deploy for homelab) ou outro provedor sem tocar no pipeline.

### 4.6 Bibliotecas Python

| Necessidade | Escolha |
|---|---|
| RSS | `feedparser` |
| HTTP | `httpx` (async) |
| Parse HTML | `selectolax` |
| Extração de artigo | `trafilatura` |
| Fuzzy match | `rapidfuzz` |
| Normalização | `unidecode` |
| Modelos | `pydantic` v2 |
| LLM | `ollama` |
| Bluesky | `atproto` |
| X | `httpx` direto |
| CLI | `typer` |
| Config | `pydantic-settings` |
| Log | `structlog` |

**Evitar:** `newspaper3k` (abandonado), `scrapy` (pesado demais para 2 fontes),
`Playwright` (desnecessário sem o ge).
