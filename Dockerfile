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
# `--chown` define o dono já na cópia — evita um `chown -R` sobre o .venv
# (dezenas de milhares de arquivos), que no overlay duplica a camada e é lento.
COPY --from=builder --chown=vascobot:vascobot /app/.venv /app/.venv
COPY --from=builder --chown=vascobot:vascobot /app/src /app/src
COPY --from=builder --chown=vascobot:vascobot /app/migrations /app/migrations
COPY crontab /etc/cron.d/vascobot
COPY --chown=vascobot:vascobot docker/entrypoint.sh /app/entrypoint.sh

# /etc/cron.d/vascobot fica root (formato com campo de usuário, lido pelo daemon).
# Nada de `crontab -u` — os dois formatos são incompatíveis.
RUN chmod 0644 /etc/cron.d/vascobot \
    && chmod +x /app/entrypoint.sh \
    && install -d -o vascobot -g vascobot /app/data

# cron roda como root; cada job roda como vascobot (campo de usuário no cron.d).
ENTRYPOINT ["/app/entrypoint.sh"]
