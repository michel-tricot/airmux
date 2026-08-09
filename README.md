# airllm

An LLM gateway prototype with a strict control plane / data plane split.

The **control plane** (FastAPI + Postgres) holds orgs, API keys, providers and models,
and compiles them into signed, self-contained policy bundles. The **data plane**
(bare Starlette) serves `POST /v1/chat/completions` (and `POST /v1/messages`, the Anthropic
Messages API) using only a bundle it polled
and cached on disk: auth, policy and routing happen with zero I/O on the request
path, and the data plane keeps serving even if the control plane is down.
Caller credentials are opaque secrets stored only as SHA-256 hashes; the bundle
carries the hash index, so the data plane authenticates by hash lookup and
revocation is absence from the next bundle, propagating within one poll interval.

## Getting started

You need [uv](https://docs.astral.sh/uv/), Docker (or a local Postgres), and an OpenAI API key.

```bash
uv sync --all-packages

# 0. Start the non-code dependencies (Postgres) for local development
docker compose -f docker-compose.dev.yml up -d --wait

# 1. Generate the bundle signing key pair (private to .airllm/signing.key, public alongside it)
uv run airllmcp keygen
echo 'OPENAI_API_KEY=sk-...' >> .env

# 2. Start the control plane (dev mode auto-runs migrations and reloads on change)
uv run airllmcp serve --dev

# 3. Start the console and claim the instance: the first account to sign up becomes its admin
bun install && bun run --filter '@workspace/gateway-console' dev   # http://localhost:5000

# 4. Start the data plane; it polls the bundle and goes ready
uv run airllmdp --dev
```

`uv run airllm quickstart --dev` bootstraps against that stack in one step: it targets the
control plane on `127.0.0.1:8000` and prints the console at `localhost:5000`, ahead of any
profile or `GW_CONTROL_PLANE_URL` left over from another instance. `airllm login --dev` takes
the same shortcut for an instance that is already set up.

The first human account on a fresh deployment claims it and becomes the instance
admin; every signup after that is an ordinary account. Claim a deployment before
exposing it, or provision the admin yourself with `airllmcp admin --email you@example.com`,
which is also how a second admin is granted: the bit never crosses the API.

### Docker Compose

The same stack runs under compose: Postgres comes up first, then the control
plane starts with `migrate && taxonomy && serve` (schema to head, catalog applied,
attributed to `root`), then the data plane, then the console on
`localhost:3000`, which nginx serves and which proxies `/v1` to the control
plane. There is no init service and no account provisioning at startup: claim the
instance by signing up in the console. The stack config is the checked-in
`docker/airllm.yml`.

```bash
# .env at the repo root: compose reads it for interpolation
# GW_BUNDLE_SIGNING_KEY=<base64 Ed25519 private key>
# OPENAI_API_KEY=sk-...
docker compose up -d --build --wait
```

Accounts are self-serve: sign up on the console login page (`localhost:3000`),
where the first account claims the instance, then create your organization and
mint an inference key on a workspace; `airllm login` connects the CLI through the
browser, which the console approves at `/cli`. The gateway
listens on `localhost:8080` and the control plane API on `localhost:8000`.
`docker compose down -v` resets the instance.

### The console

`apps/console` is the console. It is a bun/TypeScript workspace, separate from
the uv one, sharing `lib/api-client-react` (generated React Query hooks) and
`lib/api-zod` (generated schemas). You need [bun](https://bun.sh).

```bash
bun install                                      # once, at the repo root
bun run --filter '@workspace/gateway-console' dev   # http://localhost:5000
```

`apps/webapp` is the previous console, kept only until anything still pointing at
it is moved over. Nothing builds or serves it: compose serves `apps/console`, and
the docs describe that one.

`PORT` and `BASE_PATH` override the port and the base path. `bun run build`
typechecks the whole workspace and emits `apps/console/dist/public`, which
`bun run --filter '@workspace/gateway-console' serve` previews.

The dev server proxies `/v1` to `localhost:8000`, which `CONTROL_PLANE_URL`
overrides; under compose nginx proxies the same path to the control plane. Either
way the API answers on the console's own origin, which is what the same-site
session cookie needs. Signing in takes an account on the instance (the login page
also signs one up). Three sections live behind that: `/app` is the org console,
where the org travels in the `X-Org-Id` header the session picks, `/` is the
instance admin console, which instance admins alone can open, and `/cli` is where
`airllm login` sends the browser to approve a device login.

### Making a request

With either setup running, make a request through the gateway:

```bash
source .env
curl -s localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer $AIRLLM_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "say hi"}]}'
```

Or use the ready-made examples (streaming prints tokens as they arrive):

```bash
uv run python examples/chat.py                # non-streaming
uv run python examples/chat_stream.py        # tokens as they arrive
uv run python examples/chat_stream_raw.py    # the raw SSE wire format
uv run python examples/chat_stream_tools.py  # tool-call fragments assembling
uv run python examples/chat_multi_turn.py    # conversation history + reasoning steps
uv run python examples/chat_stream_cancel.py # abandon mid-stream, see cancelled accounting
uv run python examples/chat_errors.py        # every failure mode and its status code
uv run python examples/anthropic_chat.py         # Claude via the native Anthropic adapter
uv run python examples/anthropic_chat_stream.py  # Claude streaming
uv run --with anthropic python examples/anthropic_sdk.py  # the real Anthropic SDK via POST /v1/messages
```

The gateway also exposes Anthropic's Messages API at `POST /v1/messages`, so
Anthropic-SDK clients can point at it; the request is routed to whatever provider
the model maps to (an Anthropic-SDK call can even run on an OpenAI model).

Because Claude Code itself speaks that API, you can run it on any cataloged model
through the gateway:

```bash
scripts/claude-gateway.sh --list            # registered models
scripts/claude-gateway.sh gpt-4o-mini       # Claude Code, backed by gpt-4o-mini
scripts/claude-gateway.sh claude-sonnet-4-6
```

`taxonomy.yml` ships with a catalog of OpenAI-compatible hosted providers
(openai, anthropic, gemini, xai, deepseek, mistral, groq); after editing it, apply
with `uv run airllmcp taxonomy`. A model becomes callable as soon as its
provider's key (for example `GROQ_API_KEY`) is in `.env`.

## Everyday commands

```bash
uv run airllm --help            # commands are grouped: Resources, Testing
uv run airllm inference-keys list        # every list command takes -f table|json|text
uv run airllm inference-keys create      # flags, or interactive prompts for anything omitted
uv run airllm inference-keys revoke <id> # takes effect at the next compile
uv run airllm bundles compile   # recompile and sign after any change
```

The admin API is browsable at `http://localhost:8000/docs`; authorize with the
`GW_INSTANCE_KEY` from `.env`. Instance keys reach the `/instance` endpoints,
management keys reach one org's.

## Configuration

- `airllm.yml` holds all non-secret config for both planes, grouped by domain.
  Secrets are referenced as `env:VAR` or `file:PATH` entries and resolved at load.
  Refs also interpolate inside strings as `${env:VAR}` / `${file:PATH}`, e.g.
  `url: postgresql+asyncpg://${env:DB_USER}:${env:DB_PASSWORD}@db:5432/airllm`;
  a string with any unresolvable ref loads as null and fails validation instead
  of producing a half-filled value.
- `.env` holds the secrets: the bundle signing key pair, admin and data plane
  bearers, provider API keys. Nothing maintains it for you: `airllmcp keygen`
  writes the key pair to files, and tokens are minted through the API or the
  CLI and pasted in.
- Precedence: explicit environment variable, then the config file, then defaults.

## Development

```bash
uv run pytest                   # unit tests for all packages
uv run pytest tests/acceptance  # black-box scenarios against real processes
uv run ruff format --check .    # formatting
uv run ruff check .             # lint, including the plane boundary rules
uv run ty check .               # types, whole workspace
uv run lint-imports             # data plane may never import the control plane or a database
./scripts/export-openapi.sh       # re-export lib/api-spec/openapi.yaml from the routes
./scripts/generate-api-models.sh  # regenerate lib/api-models from that spec
```

The bun workspace is checked separately, and CI does not cover it yet:

```bash
bun run typecheck               # lib/* project references, then the console
bun run build                   # typecheck, then build apps/console
bun run --cwd lib/api-spec codegen  # regenerate lib/api-client-react and lib/api-zod
```

`lib/api-spec/openapi.yaml` is the committed contract every client generates
from: `lib/api-models` for python, `lib/api-client-react` and `lib/api-zod` for
typescript. It is exported from the control plane routes, and CI fails on drift
in the spec or in the python models, so change a route and re-export rather than
hand-editing the spec or anything under a `generated/` directory. Orval unwraps
the `{"data": ...}` envelope out of the typescript types and `customFetch` strips
it at runtime, so the console's hooks return payloads.

Repo layout: `lib/contract` is the only code both planes share (bundle and
event schemas, signing, tokens). `apps/control-plane`, `apps/data-plane`,
`apps/cli`, `lib/contract` and `lib/api-models` are uv workspace members.
`apps/console` and the other `lib/*` packages are the bun workspace holding the
console and its generated clients; `apps/webapp` is the deprecated previous
console and is not built by anything.
The full design spec lives in `notes/PROTOTYPE.md`, and the working rules in
`CLAUDE.md`.
