# Development

Run commands from the repository root. Use Python 3.13+, uv, Bun, and Docker with Compose. The
Python and JavaScript workspaces each have a committed lockfile.

## Install and initialize

```sh
uv sync --all-packages --frozen
bun install --frozen-lockfile
uv run pre-commit install
docker compose -f docker-compose.dev.yml up -d --wait
uv run airllmcp bootstrap-keygen
uv run airllmcp migrate
uv run airllmcp taxonomy --file taxonomy/taxonomy.yml
```

Run `bootstrap-keygen` once. It creates `.airllm/dataplane.key`; retain it with the local database.
The control plane authorizes that gateway credential at startup. This leaves the instance owner
unclaimed so you can use the normal onboarding flow.

Start these in separate terminals:

| Process | Command | Address |
| --- | --- | --- |
| Control plane | `uv run airllmcp serve --dev` | `http://127.0.0.1:8000` |
| Gateway | `uv run airllmdp serve --config airllm.yml` | `http://127.0.0.1:8080` |
| Console | `bun run dev` | `http://127.0.0.1:5000` |

Open the console at `127.0.0.1:5000` to sign up, add a provider credential, and create an inference
key. Use the same hostname throughout a session. Vite forwards `/api` and `/inf` to the backends.
Use `uv run airllm quickstart --url http://127.0.0.1:5000` for interactive CLI setup instead.

`airllm.yml` configures source development. It reads `DATABASE_URL` and `GW_CONSOLE_URL` when set;
otherwise it uses the addresses above. `.env` is loaded automatically. Provider credentials for
this managed stack are added through the console or CLI and stored under `.airllm/secrets`.

To change ports, keep `GW_CONSOLE_URL`, the servers' `--port` arguments, and Vite's `PORT`,
`CONTROL_PLANE_URL`, and `DATA_PLANE_URL` consistent. Stop the production Docker stack if its
published port 8080 conflicts with the source gateway.

## Gateway only

For adapter work or trying inference without the management stack:

```sh
export OPENAI_API_KEY='your-provider-key'
uv run airllmdp serve --config airllm.standalone.yml
```

In another terminal:

```sh
curl http://127.0.0.1:8080/inf/v1/chat/completions \
  -H 'Authorization: Bearer sk-inf-standalone-dev' \
  -H 'Content-Type: application/json' \
  -d '{"model":"gpt-5-nano","messages":[{"role":"user","content":"Say hello"}]}'
```

Edit `bundle.standalone.yml` to change routing. This mode has a public development inference key,
uses environment-backed provider keys, and discards usage. Keep it on your development machine.

## Checks

```sh
uv run ruff format .
uv run ruff check .
uv run ty check .
uv run lint-imports
uv run pytest -n auto
```

Control-plane unit tests need no database:

```sh
uv run pytest apps/control-plane/tests/unit
```

Integration tests start a throwaway Postgres container, then clone a template database per test.
Docker must be running. To reuse a disposable Postgres server, set `AIRLLM_TEST_PG_URL`; tests need
permission to create databases. Never point that setting at a production database.

Request-path changes also need the black-box scenarios and a real request to a running gateway:

```sh
uv run pytest tests/acceptance/scenarios
```

For console changes:

```sh
bun run format:check
bun run lint
bun run typecheck
bun run coverage
bun run build
```

Deployment checks exercise fresh Docker installations, streaming, outage behavior, and persistent
state. See [Docker verification](deployment/docker.md#verification). Their HTTP upstream is a local
test service, so they need no paid provider credentials.

## Generated APIs

After changing an API or canonical schema:

```sh
./scripts/export-openapi.sh
./scripts/generate-api-models.sh
./scripts/export-completion-schemas.sh
bun run codegen
```

Commit generated changes with their source. Do not edit generated models or clients by hand.

## Reset local development

Stop the source processes first. The following deletes the development database and local keys,
provider credentials, gateway cache, and usage outbox:

```sh
docker compose -f docker-compose.dev.yml down -v
rm -rf .airllm
```

Repeat initialization afterward. Avoid resetting the database without its matching local state.

## Repository map

| Path | Purpose |
| --- | --- |
| `apps/control-plane` | Management API, catalog, bundles, event ingestion |
| `apps/data-plane` | Inference, adapters, routing, streaming, metering |
| `apps/console` | React management console |
| `apps/cli` | Setup and resource-management CLI |
| `lib/contract` | The contract shared by both planes |
| `lib/api-models`, `lib/api-client-react` | Generated API clients |
| `taxonomy`, `model-audit` | Provider catalog and recorded evidence |
| `deploy` | Container configuration and provider deployment assets |
| `tests/acceptance`, `tests/deployment` | Running-gateway and Docker checks |
