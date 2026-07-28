#!/bin/sh
set -eu

# O cron NÃO herda o ambiente do container — jobs rodam com env mínimo. Então
# despejamos o ambiente atual (com as credenciais do env_file) num arquivo que
# o job do cron carrega. shlex.quote garante que valores com espaço/parênteses
# (ex.: USER_AGENT) sejam sourced com segurança.
echo "vascobot: exportando ambiente para o cron..."
python -c "import os, shlex; print(chr(10).join(f'export {k}={shlex.quote(v)}' for k, v in os.environ.items()))" > /app/runtime_env.sh
chmod 600 /app/runtime_env.sh
chown vascobot:vascobot /app/runtime_env.sh

echo "vascobot: aplicando migrations..."
su -s /bin/sh -c '. /app/runtime_env.sh; vascobot db migrate' vascobot

echo "vascobot: iniciando cron em foreground (TZ=${TZ:-America/Sao_Paulo})..."
# cron roda como root; cada job (definido em /etc/cron.d/vascobot) roda como
# o usuário vascobot e carrega /app/runtime_env.sh antes de executar.
exec cron -f
