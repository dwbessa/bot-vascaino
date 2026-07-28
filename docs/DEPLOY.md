# Deploy em produção — Vasco Digest Bot

Modo autônomo (sem aprovação), só Bluesky, Docker Compose com cron interno.
Grade: 00, 06, 09, 12, 15, 18, 21h (America/Sao_Paulo).

## Pré-requisitos na máquina de prod

- Docker + plugin `docker compose`
- `git`
- Saída de rede (nada de inbound)

## 1. Clonar

```bash
git clone git@github.com:dwbessa/agrega-vasco.git
cd agrega-vasco
```

## 2. Criar o `.env` (NÃO commitado)

```bash
cat > .env <<'EOF'
SOURCES_ENABLED=netvasco,supervasco
MAX_LOOKBACK_HOURS=8
USER_AGENT="VascoDigestBot/1.0 (+contato@exemplo.com)"

OLLAMA_HOST=https://ollama.com
OLLAMA_API_KEY=COLE_SUA_CHAVE
CLASSIFY_MODEL=deepseek-v4-flash
SUMMARIZE_MODEL=qwen3.5:397b
CLASSIFY_CONFIDENCE_THRESHOLD=0.7
CLASSIFY_BATCH_SIZE=20
INCLUDE_INSTITUTIONAL=true

BLUESKY_ENABLED=true
BLUESKY_HANDLE=botvascaino.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

X_ENABLED=false

REQUIRE_APPROVAL=false
MAX_POSTS_PER_THREAD=4
LOG_LEVEL=INFO
TZ=America/Sao_Paulo
EOF
chmod 600 .env
```

`DB_PATH` e `BLUESKY_SESSION_PATH` são setados pelo `docker-compose.yml` para
`/app/data/...` (volume) — não precisa colocar no `.env`.

## 3. Build

```bash
docker compose build
```

## 4. Validar ANTES de deixar autônomo

**4.1 App funciona no container (não publica):**
```bash
docker compose run --rm vascobot vascobot run --dry-run
```
Espere um JSON com `"collected": N` e `"digests": M`. Sem erro de rede/LLM.

**4.2 O cron vai ter as credenciais** (cron não herda o env do container; o
entrypoint exporta para `/app/runtime_env.sh`):
```bash
docker compose up -d
docker compose exec vascobot sh -c '. /app/runtime_env.sh; env | grep -E "OLLAMA_API_KEY|BLUESKY_HANDLE"'
```
Tem que listar as duas variáveis. Se listar, o job agendado vai funcionar.

## 5. Subir (cron ativo)

```bash
docker compose up -d
docker compose logs -f          # acompanha o boot
```
A partir daqui o cron dispara sozinho nos 7 horários e **publica sem aprovação**.

> Primeira execução: o watermark começa vazio, então ela coleta o backlog
> visível (~100 notícias) e posta um digest maior. As execuções seguintes só
> pegam o que é novo desde a última.

## 6. (Opcional) Disparar uma execução real agora

Sem esperar o próximo horário da grade — **isto publica de verdade**:
```bash
docker compose exec vascobot su -s /bin/sh -c '. /app/runtime_env.sh; vascobot run' vascobot
```

## 7. Operação do dia a dia

```bash
# log das execuções do cron
docker compose exec vascobot tail -f /app/data/vascobot.log

# resumo por dia + alertas
docker compose exec vascobot su -s /bin/sh -c '. /app/runtime_env.sh; vascobot stats --days 7' vascobot

# atualizar o código
git pull && docker compose build && docker compose up -d

# parar / reiniciar
docker compose down
docker compose up -d
```

## Backup

O estado (banco SQLite + sessão do Bluesky) vive no volume `vascobot-data`:
```bash
docker run --rm -v vascobot-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/vascobot-data.tgz -C /data .
```

## Desligar publicação em emergência

- Bluesky: `BLUESKY_ENABLED=false` no `.env` → `docker compose up -d`.
- Voltar a exigir aprovação: `REQUIRE_APPROVAL=true` → as execuções passam a
  deixar tudo `pending`, e você libera com `vascobot approve` (ver README).
