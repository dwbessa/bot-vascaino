# Spec — Vasco Digest Bot

**Feature ID:** 001-vasco-digest
**Status:** Aprovado (decisões de 2026-07-27 incorporadas)
**Autor:** Daniel

---

## 1. Problema

Notícias do Club de Regatas Vasco da Gama estão espalhadas em vários portais. Um
torcedor que quer acompanhar futebol feminino ou as categorias de base precisa
garimpar entre dezenas de posts diários, a maioria sobre o time profissional
masculino ou sobre modalidades fora do futebol (futsal, basquete, natação,
e-sports, futmesa). Não existe hoje resumo periódico segmentado por categoria.

## 2. Objetivo

Publicar, 7 vezes por dia, um resumo condensado das notícias do Vasco desde a
última execução, **separado por categoria**, em **thread** no Bluesky e no X.

## 3. Escopo

### 3.1 Categorias

| ID | Nome | Descrição |
|---|---|---|
| `profissional` | Futebol masculino profissional | Jogos, elenco, mercado, comissão técnica **e pauta institucional** (SAF, CEO, investidor, eleição, patrocínio, estádio, sócio-torcedor) |
| `feminino` | Futebol feminino | Elenco principal feminino, futebol de campo |
| `base_sub20` | Base Sub-20 | Futebol de campo masculino Sub-20 |
| `base_sub17` | Base Sub-17 | Futebol de campo masculino Sub-17 **e Sub-16** |
| `base_sub15` | Base Sub-15 | Futebol de campo masculino Sub-15 |
| `descartado` | — | Fora de escopo, não publicado |

**Fora de escopo (`descartado`):** futsal (todas as idades e gêneros), basquete,
vôlei, natação, remo, atletismo, judô, e-sports, futmesa, futevôlei, polo
aquático, esporte amador, conteúdo histórico/efemérides, blogs de opinião,
wallpapers, Sub-14 e categorias menores, notas de torcidas organizadas.

> ⚠️ **Armadilha:** `Futsal Feminino Base: ...` e `Futsal Base: Vasco x Barra
> Sub-12` contêm "Feminino" e "Sub-XX" mas **não** são futebol. A exclusão roda
> **antes** da classificação positiva. Caso de teste obrigatório.

### 3.2 Fontes (v1)

| Fonte | Domínio | Método |
|---|---|---|
| NetVasco | `netvasco.com.br` | RSS `/news/rss.xml` — confirmado |
| SuperVasco | `supervasco.com` | HTML da listagem `/ultimas-noticias-vasco/` |

`ge.globo` foi **removido do escopo**. A arquitetura permite adicionar fontes
(`crvascodagama.com`, `vasco.com.br`) sem alterar o pipeline.

### 3.3 Fora de escopo (v1)

Instagram, Threads, Telegram, Facebook, geração de imagens/cards, interface web,
tradução.

---

## 4. Requisitos funcionais

### RF-01 — Coleta
Extrair de cada fonte: URL canônica, ID externo, título, lide, corpo, timestamp
de publicação (aware, America/Sao_Paulo), fonte e autor quando disponível.

### RF-02 — Janela por watermark
Processar notícias posteriores à **última marca d'água processada com sucesso**,
limitada a um lookback máximo (default 8h).

> A grade (06, 09, 12, 15, 18, 21, 00 BRT) deixa um vão de 6h entre 00h e 06h.
> Janela fixa de 3h perderia tudo publicado entre 00h e 03h — e os portais
> publicam nesse intervalo (observado no NetVasco: 01:54, 03:08, 04:39).

### RF-03 — Classificação em três camadas
Cada notícia recebe exatamente uma categoria, com score de confiança e método
(`regra` ou `llm`). Abaixo do limiar → `pending_review`, não publica.

**A maior parte do volume não vem prefixada.** O profissional masculino é o
carro-chefe dos portais e raramente traz marcação de categoria. Portanto o LLM
não é fallback ocasional: é ele quem decide, no bolo sem prefixo, o que é
efetivamente futebol profissional e o que é descarte.

### RF-04 — Deduplicação
Agrupar em *cluster* notícias do mesmo fato, inclusive de fontes diferentes com
títulos distintos. O cluster preserva todas as URLs; a mais antiga é canônica.

> Duplicação cross-fonte é real: SuperVasco republica `crvascodagama.com` e cita
> NetVasco (`NTV: ...`).

### RF-05 — Sumarização
Resumo em pt-BR, factual, sem opinião, sem afirmar nada que não esteja no
material coletado.

### RF-06 — Composição em thread
**Thread nas duas plataformas.** Post-raiz identifica categoria e intervalo;
replies trazem os bullets; o último traz as fontes.
- Bluesky: 300 graphemes/post, links como *facets*.
- X: 280 chars (ou 25.000 se Premium), política de link configurável.

### RF-07 — Publicação desacoplada por plataforma
X e Bluesky publicam de forma independente. `X_ENABLED=false` remove o X do
pipeline inteiro (inclusive da composição), sem afetar o Bluesky nem corromper
histórico ou idempotência.

### RF-08 — Idempotência
Chave derivada de `(run_id, categoria, plataforma, índice_no_thread)`, UNIQUE.

### RF-09 — Agendamento
06:00, 09:00, 12:00, 15:00, 18:00, 21:00 e 00:00 em America/Sao_Paulo via
`zoneinfo`.

### RF-10 — Dry-run e fila de aprovação
`--dry-run` gera tudo sem publicar. `REQUIRE_APPROVAL=true` deixa posts
`pending` até liberação manual. **Ligado nas 2 primeiras semanas.**

### RF-11 — Degradação do LLM
Se o provedor de LLM ficar indisponível, o run é marcado `partial`, os artigos
não classificados ficam `pending_review` e **o watermark não avança para eles**.
Nunca publicar com classificação incompleta.

### RF-12 — Atribuição e crawling responsável
Todo post credita a(s) fonte(s). Respeitar `robots.txt`, User-Agent
identificável com contato, rate limit por domínio, `ETag`/`If-Modified-Since`.

---

## 5. Requisitos não-funcionais

| ID | Requisito |
|---|---|
| RNF-01 | Execução completa < 3 minutos |
| RNF-02 | Custo do X registrado e projetado a cada run; teto opcional |
| RNF-03 | Estado em arquivo único, backup trivial |
| RNF-04 | Segredos só por variável de ambiente, nunca em código ou log |
| RNF-05 | Log estruturado JSON com contadores por etapa |
| RNF-06 | Falha de uma fonte não derruba a execução |
| RNF-07 | Nenhum texto de terceiro reproduzido literalmente |
| RNF-08 | Provedor de LLM plugável (Ollama Cloud ↔ Ollama local ↔ outro) |

---

## 6. Critérios de aceite

- [ ] **CA-01** Coleta ≥ 90% das notícias publicadas desde a última execução nas 2 fontes.
- [ ] **CA-02** No CSV rotulado de 100 manchetes: ≥ 95% de precisão em `descartado` e ≥ 90% de acurácia geral.
- [ ] **CA-03** Mesmo fato em NetVasco e SuperVasco cai no mesmo cluster.
- [ ] **CA-04** Nenhum post excede o limite da plataforma.
- [ ] **CA-05** Reexecutar a mesma janela não publica nada novo.
- [ ] **CA-06** Uma fonte fora do ar não impede a publicação.
- [ ] **CA-07** Notícia publicada às 02:00 BRT aparece no digest das 06:00.
- [ ] **CA-08** Nenhum segredo em log ou stack trace.
- [ ] **CA-09** `X_ENABLED=false` → pipeline roda inteiro só com Bluesky, sem erro e sem draft órfão.
- [ ] **CA-10** LLM indisponível → run `partial`, nada publicado, watermark preservado.

---

## 7. Decisões tomadas

| # | Questão | **Decisão** |
|---|---|---|
| D1 | Link nos posts do X | **Manter links.** Implementado como `X_LINK_POLICY` (`none`/`last_post`/`all_posts`), default `last_post`. Ver research.md §3 para a projeção de custo |
| D2 | Auto-post vs aprovação | **Aprovação manual nas 2 primeiras semanas** |
| D3 | Sub-16 | **Agrupado em `base_sub17`.** Sub-14 e menores → `descartado` |
| D4 | Formato | **Thread nas duas plataformas** |
| D5 | Conteúdo sem prefixo | **LLM decide inclusão** (RF-03) |
| D6 | Conta do bot | **Nova e dedicada** |
| D7 | Hospedagem | **VPS ou homelab, a definir.** Deploy em Docker mantém as duas opções abertas |
| D8 | Teto de gasto do X | **Adiado.** Implementar o contador e a projeção agora; o teto fica opcional (`X_MONTHLY_BUDGET_USD` vazio = sem limite) |
| D9 | Provedor de LLM | **Ollama Cloud**, atrás da interface `LLMProvider` |
| D10 | ge.globo | **Removido do escopo** |
| D11 | Pauta institucional em `profissional` | **Incluída.** `INCLUDE_INSTITUTIONAL=true`. Torcida organizada e história seguem em `descartado` |

---

## 8. Questões que continuam abertas

| # | Questão | Impacto | Default proposto |
|---|---|---|---|
| **Q1** | Categoria sem notícia na janela: postar nada ou avisar? | UX | **Silêncio total** |
| **Q2** | Máximo de posts por thread | Custo no X | **4** (raiz + 2 bullets + fontes) |
| **Q3** | Especulação de mercado entra no digest? | Risco | **Sim, sempre marcada como especulação e atribuída** |
| **Q4** | Como priorizar quando `profissional` tem mais clusters que espaço? | **Novo, vindo do D11** | Ver RF-13 |

### RF-13 — Priorização dentro de `profissional`

Com a pauta institucional incluída (D11), `profissional` passa a concentrar a
maior parte do volume — e uma thread de 4 posts comporta ~2 bullets. Sem
critério, uma notícia de patrocínio pode empurrar para fora o resultado do jogo.

O sumarizador ordena os clusters por peso antes de cortar:

| Peso | Tipo |
|---|---|
| 1 | Jogo, resultado, escalação, lesão, suspensão |
| 2 | Mercado (chegada/saída confirmada), comissão técnica |
| 3 | Mercado especulado |
| 4 | Institucional (SAF, CEO, investidor, eleição, patrocínio, estádio) |

Empate de peso → mais recente primeiro. Um cluster de peso 4 nunca desloca um de
peso 1. Se sobrar espaço, o institucional entra normalmente.

> Alternativa a avaliar no soft launch: dar `MAX_POSTS_PER_THREAD=5` só para
> `profissional`, já que é o carro-chefe.

---

## 9. Riscos

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| LLM alucina reforço/transferência inexistente | Média | **Alto** | Structured output, temperatura 0, guardrail pós-LLM, aprovação humana (D2) |
| Custo do X com links acima do esperado | **Alta** | Médio | `X_LINK_POLICY`, projeção logada a cada run, `X_ENABLED` como saída de emergência |
| **Ollama Cloud sem SLA / indisponível** | Média | Médio | RF-11 + retry; `LLMProvider` permite cair para Ollama local |
| Portais mudam prefixos ou estrutura | Média | Médio | Camada LLM cobre; métrica de taxa de fallback |
| Rate limit do Bluesky | Baixa | Médio | Sessão persistida, backoff |
| Portais reclamarem do uso do conteúdo | Baixa | Alto | RNF-07, atribuição explícita, contato no User-Agent |
