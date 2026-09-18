# airmux on Replit

airmux is an LLM gateway with a FastAPI control plane, a Starlette data plane, a React/Vite console,
and the `airmux` CLI. The control plane manages organizations, workspaces, keys, providers, models,
and policy bundles. The data plane serves Chat Completions, Responses, and Messages under `/inf/v1`;
the management API lives under `/api/v1`.

Use the [development guide](docs/development.mdx) for local setup outside Replit, service commands,
checks, and the repository map. See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md)
for contribution and architecture rules, and the [configuration reference](docs/reference/configuration.mdx)
for runtime settings. This file covers the Replit-specific workflow.

## Runtime and repository

- Python 3.13 or newer with uv, as required by [pyproject.toml](pyproject.toml)
- Replit modules: Python 3.13, Node 24, Bun 1.3, and PostgreSQL 16, configured in [.replit](.replit)
- Python applications in `apps/cli`, `apps/control-plane`, and `apps/data-plane`; the console in `apps/console`
- Shared Python libraries in `lib/contract` and `lib/runtime`, generated Python API models in `lib/api-models`
- Management OpenAPI in `lib/api-spec/openapi.yaml`, generated React client in `lib/api-client-react`
- Mintlify documentation in `docs/`, with navigation in [docs.json](docs.json)

Use Bun as the JavaScript package manager and workspace runner. Run commands from the repository root.

## Replit scope

Replit manages the console artifact (`@workspace/gateway-console`). Limit Replit changes to the console
and Replit-specific configuration. Do not scaffold a replacement backend or modify the Python backend,
schemas, or migrations as part of console work. The console uses the generated client for the real control plane.

The Python services run through uv. The separate **backend: control plane** workflow supports console
development; the **Project** workflow starts only the console. Inference features also require a running
data plane, as described below.

## Console workflow

Install the locked dependencies:

```bash
uv sync --all-packages --frozen
bun install --frozen-lockfile
```

The [console artifact](apps/console/.replit-artifact/artifact.toml) starts
`bun run --filter @workspace/gateway-console dev` with `PORT=20383` and `BASE_PATH=/`.
The **Project** workflow runs this artifact, and `.replit` maps local port 20383 to external port 80.
The equivalent manual command is:

```bash
PORT=20383 bun run dev
```

The [Vite configuration](apps/console/vite.config.ts) forwards requests without removing their prefixes:

| Request prefix | Target variable | Default outside Replit | Replit setting |
| --- | --- | --- | --- |
| `/api` | `CONTROL_PLANE_URL` | `http://127.0.0.1:8000` | `.replit` sets `http://127.0.0.1:8101` |
| `/inf` | `DATA_PLANE_URL` | `http://127.0.0.1:8080` | Uses the default unless overridden |

These proxies belong to the Vite development server. The artifact's static production build needs
deployment routing for the Python APIs; see the [deployment guide](docs/deployment/index.mdx).

## Backend support workflow

Replit supplies the managed PostgreSQL connection through `DATABASE_URL`. The
[backend helper](scripts/replit-backend.sh) requires it and normalizes its PostgreSQL scheme and
`sslmode` parameter for asyncpg. It does not use the local database fallback in [airmux.yml](airmux.yml).

The checkout configuration reads the bootstrap management key from `.airmux/dataplane.key` for both planes.
Control-plane startup creates that file when it is missing. The helper loads fixtures before starting the
server, so it requires the key file to exist already; it is not a complete first-run bootstrap for a fresh
checkout. See [service initialization](docs/development.mdx#install-and-initialize) for key creation and
keep the key with its matching development database.

For an initialized checkout, run the **backend: control plane** workflow or:

```bash
./scripts/replit-backend.sh
```

The helper applies migrations, applies `taxonomy/taxonomy.yml`, loads fixtures if no users exist, and
starts `control-plane serve --dev --host 127.0.0.1 --port 8101`. Taxonomy application is explicit;
development server startup applies migrations and authorizes the configured bootstrap key.

On migration failure, the helper resets the disposable development database's `public` schema with
`DROP SCHEMA public CASCADE; CREATE SCHEMA public;`, then retries migration and continues with taxonomy,
fixtures, and startup. This destroys that schema's data. Use the helper only with the disposable Replit
development database. “Reset the db” means resetting the schema, migrating, and installing fixtures in that order.

Set `AIRMUX_CONSOLE_URL` to the public Replit preview origin when using browser authentication flows
that generate console links. Provider keys such as `OPENAI_API_KEY` are needed for real inference;
they are separate from the bootstrap management key and caller inference keys. See
[.env.example](.env.example) and the [authentication guide](docs/concepts/authentication.mdx).

For inference features, start the data plane in another terminal using the checkout configuration
and the Replit control-plane port:

```bash
AIRMUX_DATAPLANE_CONTROL_PLANE_URL=http://127.0.0.1:8101 \
  uv run airmux gateway serve --config airmux.yml --dev
```

The data plane listens on port 8080 by default. Callers send an inference key to
`/inf/v1/chat/completions`, `/inf/v1/responses`, or `/inf/v1/messages`; see the
[inference reference](docs/reference/inference.mdx).

## Validation

Use the [console checks](docs/development.mdx#console-checks) and
[Python checks](docs/development.mdx#python-checks) for the files changed.
The **console-test** workflow runs the console package's `bun run test` command.
`bun run build` at the repository root runs workspace type checking and builds the console.
