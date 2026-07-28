# syntax=docker/dockerfile:1

# ---------- builder ----------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Instala só as deps primeiro (cache de camada)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Agora o código
COPY src ./src
COPY migrations ./migrations
RUN uv sync --frozen --no-dev

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

# cron para o agendamento; tzdata para America/Sao_Paulo
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Sao_Paulo \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Usuário não-root
RUN useradd --create-home --uid 10001 vascobot

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/migrations /app/migrations
COPY crontab /etc/cron.d/vascobot
COPY docker/entrypoint.sh /app/entrypoint.sh

RUN chmod 0644 /etc/cron.d/vascobot \
    && crontab -u vascobot /etc/cron.d/vascobot \
    && chmod +x /app/entrypoint.sh \
    && mkdir -p /app/data \
    && chown -R vascobot:vascobot /app

# cron precisa de root para rodar o daemon, mas o job roda como vascobot
# (definido no crontab com o usuário no comando).
ENTRYPOINT ["/app/entrypoint.sh"]
