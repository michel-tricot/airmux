---
name: Backend setup quirks for Replit
description: Key non-obvious facts for getting the Python control plane running on Replit the first time.
---

## Python version
The workspace requires Python >=3.13. Replit's default module is python-3.12. Install `python-base-3.13` via `installProgrammingLanguage` first; uv will then find it.

## taxonomy --file path
`uv run tokkeeper-control-plane taxonomy` defaults to looking for `taxonomy.yml` next to `tokkeeper.yml` (project root). The actual file lives at `taxonomy/taxonomy.yml`. The backend script (`scripts/replit-backend.sh`) must pass `--file taxonomy/taxonomy.yml`.

**Why:** The taxonomy command's `--file` option is resolved next to the config file. The taxonomy directory is a subdirectory, not the root.

**How to apply:** `uv run tokkeeper-control-plane taxonomy --file taxonomy/taxonomy.yml` in `scripts/replit-backend.sh`.

## Control plane port
`scripts/replit-backend.sh` starts the server on port 8101 (`--port 8101`), not the default 8000. The console's Vite proxy defaults to `http://127.0.0.1:8000`. Set `CONTROL_PLANE_URL=http://127.0.0.1:8101` as a shared env var so the proxy reaches the backend.

**Why:** Port 8101 is loopback-only to stay invisible to Replit's port detector (prevents preview routing to API instead of console).

## DATABASE_URL normalization
Run the backend via `scripts/replit-backend.sh` (not raw `uv run tokkeeper-control-plane migrate`) — the script normalizes `sslmode` → `ssl` in the DATABASE_URL for asyncpg compatibility.

## Signing keys
`uv run tokkeeper-control-plane keygen` writes `.tokkeeper/signing.key` and `.tokkeeper/signing.pub`. These are file-based secrets read by `tokkeeper.yml` directly — not environment variables. The backend script runs keygen if they don't exist.

## Fixture accounts (dev only)
After fixtures seed successfully, the backend logs a table of fixture login credentials directly to stdout. Read those from the workflow log — do not store credentials here.
