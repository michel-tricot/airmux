#!/usr/bin/env bash
set -euo pipefail

# Replit development helper for the externally managed Python backend.
# The console remains the only Replit-managed application/artifact.

require_database_vars() {
  local name
  for name in PGUSER PGPASSWORD PGHOST PGPORT PGDATABASE; do
    if [[ -z "${!name:-}" ]]; then
      printf 'Missing required PostgreSQL environment variable: %s\n' "$name" >&2
      exit 1
    fi
  done
}

reset_database() {
  printf '%s\n' 'Migration failed; resetting the Replit development database.'

  # Connect to the default maintenance database so the target database is not
  # the active connection while it is being dropped.
  local admin_url="postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/postgres"
  PGPASSWORD="$PGPASSWORD" dropdb \
    --if-exists \
    --force \
    --maintenance-db="$admin_url" \
    --username="$PGUSER" \
    --host="$PGHOST" \
    --port="$PGPORT" \
    "$PGDATABASE"
  PGPASSWORD="$PGPASSWORD" createdb \
    --maintenance-db="$admin_url" \
    --username="$PGUSER" \
    --host="$PGHOST" \
    --port="$PGPORT" \
    "$PGDATABASE"
}

require_database_vars

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
database_url="postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${PGDATABASE}"
if [[ "$(PGPASSWORD="$PGPASSWORD" psql "$database_url" -tAc \
  "SELECT to_regclass('public.user') IS NOT NULL;" | tr -d '[:space:]')" == "t" ]] &&
  [[ "$(PGPASSWORD="$PGPASSWORD" psql "$database_url" -tAc \
  "SELECT EXISTS (SELECT 1 FROM public.\"user\" LIMIT 1);" | tr -d '[:space:]')" == "t" ]]; then
  printf '%s\n' 'fixtures already loaded; skipping fresh-database seed.'
else
  uv run airllmcp fixtures
fi

# Replit's workflow monitor needs the service reachable on the workspace
# network; the CLI defaults to loopback for local-only development.
exec uv run airllmcp serve --dev --host 0.0.0.0