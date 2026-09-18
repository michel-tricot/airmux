# airmux

An LLM gateway prototype with a strict control plane / data plane split, plus the console (Bun workspace) that serves both the org and instance admin views.

## What it does

- **Control plane** (FastAPI + Postgres): manages orgs, API keys, providers, and models; compiles policy bundles
- **Data plane** (bare Starlette): serves `POST /v1/chat/completions` and `POST /v1/messages` (Anthropic API) with zero I/O on the hot path
- **Console** (`apps/console`): React/Vite admin and org console
- **CLI** (`apps/cli`): `airmux` commands for running the planes and managing the gateway

## Stack

- Python 3.12, managed with `uv` (workspace with multiple packages)
- Node 24 / Bun for the React console
- PostgreSQL (required — used by the control plane)
- FastAPI (control plane), Starlette (data plane)

## Running locally (outside Replit)

See README.md for the full getting-started guide. The short version:

```bash
uv sync --all-packages
docker compose -f docker-compose.dev.yml up -d --wait   # Postgres
# add OPENAI_API_KEY to .env
uv run airmux control-plane migrate
uv run airmux control-plane taxonomy --file taxonomy/taxonomy.yml
uv run airmux control-plane serve --dev              # control plane on :8000
# sign up at the console: the first account claims the instance
uv run airmux gateway serve --dev           # data plane on :8080
```

## Required secrets / env vars

See `.env.example`. Key variables:

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Route requests to OpenAI (and other providers) |
| `AIRMUX_MANAGEMENT_KEY` | Bearer for control-plane APIs |
| `AIRMUX_DATAPLANE_TOKEN` | Data plane → control plane bearer |
| `AIRMUX_INFERENCE_KEY` | Caller inference key |

Development control-plane startup applies migrations, ensures the configured shared pool key exists, and authorizes the key.
Taxonomy application remains explicit.

## Project layout

```
apps/
  cli/           # public airmux CLI
  control-plane/ # FastAPI admin + compile API
  data-plane/    # Starlette inference gateway
packages/
  contract/      # shared bundle/event schemas and tokens
apps/console/    # React/Vite admin console ("Precision Control Room") — the only Replit-managed app
lib/             # Bun workspace libs
  api-spec/         # openapi.yaml — API contract (codegen via orval)
  api-client-react/ # generated react-query client
docs/            # MkDocs site
examples/        # ready-made curl / Python scripts
notes/           # design docs and prototype spec
scripts/         # shell helpers + Bun workspace scripts package
```

## New admin console (Bun workspace)

Tenancy model: management keys can be bound to the instance, an organization, or a workspace; roles grant standing authority and each key narrows it with explicit permissions.

Replit only manages the console (`apps/console`, workspace package `@workspace/gateway-console`). The backend/API/proxy (control plane, data plane) are the Python apps under `apps/`, managed externally with uv — do not scaffold or run backends from Replit. The console already talks to the real backend: `lib/api-spec/openapi.yaml` is exported from the control plane routes, and the clients are generated from it.

```bash
bun install
bun run build        # typecheck + build all workspace packages
bun run typecheck
```

## Replit development workflow

When working in Replit, changes are limited to Replit-specific configuration
and the console in `apps/console`. Do not modify, rewrite, migrate, scaffold,
or add schema changes to the Python backend or its migrations.
The registered Replit artifact is the console and its managed workflow runs:

```bash
bun run --filter @workspace/gateway-console dev
```

The root equivalent is `bun run dev`. The console expects the control plane
on `http://127.0.0.1:8000` by default and proxies `/v1` requests there.

When the backend is needed for local console development, Replit's managed
PostgreSQL provides the runtime-managed `DATABASE_URL` connection string.
`airmux.yml` reads that variable directly; without it the config falls back to
the local `docker-compose.dev.yml` database. Run the bootstrap from the
repository root:

```bash
./scripts/replit-backend.sh
```

That script runs the required sequence:

1. `uv run airmux control-plane migrate`, resetting only the disposable Replit development database when migration fails
2. `uv run airmux control-plane taxonomy --file taxonomy/taxonomy.yml`
3. `uv run airmux control-plane fixtures`
4. `uv run airmux control-plane serve --dev` (the helper binds it to Replit's loopback backend port)

If there is any migration incompatibility, the script must start the Replit
development database from scratch: drop and recreate it, then run the full
sequence again (`migrate`, `taxonomy`, `fixtures`, and `serve`). This reset is
intentionally destructive and is only for the Replit development database. The
backend support workflow is separate from the console artifact; Replit code
changes remain console-only.

## Development commands

```bash
uv run pytest                    # unit tests
uv run pytest tests/acceptance/full_stack/scenarios   # black-box acceptance tests
uv run ruff format --check .     # formatting
uv run ruff check .              # lint
uv run ty check .                # type checking
```

## User preferences

- Use Bun (not pnpm) as the JS package manager and workspace runner for this project.
- "Reset the db" always means: drop the schema (`DROP SCHEMA public CASCADE; CREATE SCHEMA public;`), run migrations, then install fixtures — in that order.
