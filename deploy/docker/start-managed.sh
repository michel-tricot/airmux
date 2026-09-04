#!/usr/bin/env sh
set -eu
if [ -n "${RENDER_EXTERNAL_URL:-}" ] && [ "${GW_CONSOLE_URL:-http://localhost:8080}" = http://localhost:8080 ]; then
  export GW_CONSOLE_URL="$RENDER_EXTERNAL_URL"
fi
airllmcp migrate --config /app/deploy/docker/migrate.yml
exec /app/deploy/docker/start-all.sh
