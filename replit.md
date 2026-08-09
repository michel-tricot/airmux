# airllm

An LLM gateway prototype with a strict control plane / data plane split, plus a new admin console (Bun workspace, merged from a separate Replit project that briefly lived in `webapp2/`).

## What it does

- **Control plane** (FastAPI + Postgres): manages orgs, API keys, providers, and models; compiles signed policy bundles
- **Data plane** (bare Starlette): serves `POST /v1/chat/completions` and `POST /v1/messages` (Anthropic API) with zero I/O on the hot path
- **Console** (`apps/webapp`): React/Vite admin UI
- **CLI** (`apps/cli`): `airllm` and `airllmcp` commands for managing the gateway

## Stack

- Python 3.12, managed with `uv` (workspace with multiple packages)
- Node 20 / Bun for the React console
- PostgreSQL (required — used by the control plane)
- FastAPI (control plane), Starlette (data plane)

## Running locally (outside Replit)

See README.md for the full getting-started guide. The short version:

```bash
uv sync --all-packages
docker compose -f docker-compose.dev.yml up -d --wait   # Postgres
uv run airllmcp init --email you@example.com
# add OPENAI_API_KEY to .env
uv run airllmcp serve --dev     # control plane on :8000
uv run airllmdp --dev           # data plane on :8080
```

## Required secrets / env vars

See `.env.example`. Key variables:

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Route requests to OpenAI (and other providers) |
| `GW_SIGNING_KEY` | Ed25519 private key — signs bundles and tokens |
| `GW_BUNDLE_PUBLIC_KEY` | Ed25519 public key — data plane verifies bundles |
| `GW_ADMIN_TOKEN` | Bearer for the admin API |
| `GW_DP_TOKEN` | Data plane → control plane bearer |
| `AIRLLM_TOKEN` | Caller inference key (minted by `airllmcp init`) |

`uv run airllmcp init` generates and writes the `GW_*` secrets automatically.

## Project layout

```
apps/
  cli/           # airllm / airllmcp CLI
  control-plane/ # FastAPI admin + compile API
  data-plane/    # Starlette inference gateway
  webapp/        # older React/Vite console (port 3000)
packages/
  contract/      # shared bundle/event schemas, signing, tokens
apps/console/    # React/Vite admin console ("Precision Control Room") — the only Replit-managed app
lib/             # Bun workspace libs
  api-spec/         # openapi.yaml — API contract (codegen via orval)
  api-zod/          # generated zod schemas
  api-client-react/ # generated react-query client
docs/            # MkDocs site
examples/        # ready-made curl / Python scripts
notes/           # design docs and prototype spec
scripts/         # shell helpers + Bun workspace scripts package
```

## New admin console (Bun workspace)

Tenancy model: organizations → (members, management keys, workspaces); workspaces → (workspace members, inference keys); users are top-level and can belong to multiple orgs.

Replit only manages the webapp (`apps/console`, workspace package `@workspace/gateway-console`). The backend/API/proxy (control plane, data plane) are the Python apps under `apps/`, managed externally with uv — do not scaffold or run backends from Replit. To wire the console to the real backend, replace `lib/api-spec/openapi.yaml` with the control plane's OpenAPI spec and re-run codegen.

```bash
bun install
bun run build        # typecheck + build all workspace packages
bun run typecheck
```

## Development commands

```bash
uv run pytest                    # unit tests
uv run pytest tests/acceptance   # black-box acceptance tests
uv run ruff format --check .     # formatting
uv run ruff check .              # lint
uv run ty check .                # type checking
```

## User preferences

- Use Bun (not pnpm) as the JS package manager and workspace runner for this project.
