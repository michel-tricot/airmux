# airllm

An LLM gateway prototype with a strict control plane / data plane split.

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
  webapp/        # React/Vite console (port 3000)
packages/
  contract/      # shared bundle/event schemas, signing, tokens
docs/            # MkDocs site
examples/        # ready-made curl / Python scripts
notes/           # design docs and prototype spec
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

<!-- Add any workspace preferences here -->
