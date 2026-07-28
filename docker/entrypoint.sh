#!/bin/sh
set -eu

# Migra o banco na subida (idempotente) e sobe o cron em foreground.
# O .env é injetado via docker-compose (env_file); as variáveis já estão
# no ambiente do processo.

echo "vascobot: aplicando migrations..."
su -s /bin/sh -c "cd /app && vascobot db migrate" vascobot

echo "vascobot: iniciando cron (TZ=$TZ)..."
# cron precisa rodar como root; o job dentro do crontab roda como vascobot.
exec cron -f
