#!/usr/bin/env bash
set -euo pipefail

# Replit development helper for the externally managed Python backend.
# The console remains the only Replit-managed application/artifact.

require_database_url() {
  if [[ -z "${DATABASE_URL:-}" ]]; then
    printf 'Missing required database environment variable: DATABASE_URL\n' >&2
    exit 1
  fi
}

reset_database() {
  printf '%s\n' 'Migration failed; resetting the Replit development database.'

  # DATABASE_URL carries the host, credentials, and target database. Connect
  # to the default maintenance database so the target is not active while it
  # is being dropped.
  local maintenance_url
  maintenance_url="$(DATABASE_URL="$DATABASE_URL" python - <<'PY'
import os
from urllib.parse import urlsplit, urlunsplit

url = os.environ["DATABASE_URL"]
parts = urlsplit(url)
scheme = parts.scheme.removesuffix("+asyncpg")
if scheme not in {"postgres", "postgresql"} or not parts.netloc:
    raise SystemExit("DATABASE_URL must be a PostgreSQL connection URL")
print(urlunsplit((scheme, parts.netloc, "/postgres", parts.query, parts.fragment)))
PY
)"

  dropdb \
    --if-exists \
    --force \
    --maintenance-db="$maintenance_url" \
    "$DATABASE_URL"
  createdb \
    --maintenance-db="$maintenance_url" \
    "$DATABASE_URL"
}

require_database_url

if [[ ! -f .airllm/signing.key || ! -f .airllm/signing.pub ]]; then
  uv run airllmcp keygen
fi

if ! uv run airllmcp migrate; then
  reset_database
  uv run airllmcp migrate
fi

uv run airllmcp taxonomy

# Fixtures are intentionally fresh-database-only. Keep the workflow restartable
# after the first successful seed without hiding real fixture errors.
if [[ "$(psql "$DATABASE_URL" -tAc \
  "SELECT to_regclass('public.user') IS NOT NULL;" | tr -d '[:space:]')" == "t" ]] &&
  [[ "$(psql "$DATABASE_URL" -tAc \
  "SELECT EXISTS (SELECT 1 FROM public.\"user\" LIMIT 1);" | tr -d '[:space:]')" == "t" ]]; then
  printf '%s\n' 'fixtures already loaded; skipping fresh-database seed.'
else
  uv run airllmcp fixtures
fi

# Replit's workflow monitor needs the service reachable on the workspace
# network; the CLI defaults to loopback for local-only development.
exec uv run airllmcp serve --dev --host 0.0.0.0