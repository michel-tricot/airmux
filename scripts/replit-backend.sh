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

normalize_database_url() {
  # Replit's managed URL uses libpq's sslmode query parameter. asyncpg expects
  # the same setting under ssl, so normalize it only in this Replit helper.
  DATABASE_URL="$(DATABASE_URL="$DATABASE_URL" python - <<'PY'
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

url = os.environ["DATABASE_URL"]
parts = urlsplit(url)
if parts.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"} or not parts.netloc:
    raise SystemExit("DATABASE_URL must be a PostgreSQL connection URL")

scheme = "postgresql+asyncpg" if parts.scheme in {"postgres", "postgresql"} else parts.scheme
query = [
    ("ssl" if key == "sslmode" else key, value)
    for key, value in parse_qsl(parts.query, keep_blank_values=True)
]
print(urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)))
PY
)"
  export DATABASE_URL
}

libpq_database_url() {
  # psql/dropdb use libpq URL syntax, while the application uses asyncpg URL
  # syntax. Derive the former locally without introducing another env var.
  DATABASE_URL="$DATABASE_URL" python - <<'PY'
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

url = os.environ["DATABASE_URL"]
parts = urlsplit(url)
query = [
    ("sslmode" if key == "ssl" else key, value)
    for key, value in parse_qsl(parts.query, keep_blank_values=True)
]
scheme = parts.scheme.removesuffix("+asyncpg")
print(urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)))
PY
}

reset_database() {
  printf '%s\n' 'Migration failed; resetting the Replit development database.'

  # DATABASE_URL carries the host, credentials, and target database. Connect
  # to the default maintenance database so the target is not active while it
  # is being dropped.
  local libpq_url maintenance_url
  libpq_url="$(libpq_database_url)"
  maintenance_url="${libpq_url%/*}/postgres"

  dropdb \
    --if-exists \
    --force \
    --maintenance-db="$maintenance_url" \
    "$libpq_url"
  createdb \
    --maintenance-db="$maintenance_url" \
    "$libpq_url"
}

require_database_url
normalize_database_url

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
libpq_url="$(libpq_database_url)"
if [[ "$(psql "$libpq_url" -tAc \
  "SELECT to_regclass('public.user') IS NOT NULL;" | tr -d '[:space:]')" == "t" ]] &&
  [[ "$(psql "$libpq_url" -tAc \
  "SELECT EXISTS (SELECT 1 FROM public.\"user\" LIMIT 1);" | tr -d '[:space:]')" == "t" ]]; then
  printf '%s\n' 'fixtures already loaded; skipping fresh-database seed.'
else
  uv run airllmcp fixtures
fi

# Loopback-only on purpose: the console's Vite proxy reaches the backend at
# 127.0.0.1:8001, and keeping the port invisible to Replit's port detector
# guarantees the preview can never route to the API instead of the console.
exec uv run airllmcp serve --dev --host 127.0.0.1 --port 8001