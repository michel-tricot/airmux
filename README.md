# airllm

An LLM gateway prototype with a strict control plane / data plane split.

The **control plane** (FastAPI + SQLite) holds orgs, API keys, providers and models,
and compiles them into signed, self-contained policy bundles. The **data plane**
(bare Starlette) serves `POST /v1/chat/completions` (and `POST /v1/messages`, the Anthropic
Messages API) using only a bundle it polled
and cached on disk: auth, policy and routing happen with zero I/O on the request
path, and the data plane keeps serving even if the control plane is down.
Caller credentials are opaque secrets stored only as SHA-256 hashes; the bundle
carries the hash index, so the data plane authenticates by hash lookup and
revocation is absence from the next bundle, propagating within one poll interval.

## Getting started

You need [uv](https://docs.astral.sh/uv/) and an OpenAI API key.

```bash
uv sync --all-packages

# 1. Set up everything: keys, config, schema, admin, org, tokens, bundle v1 (applies taxonomy.yml)
uv run airllmcp init --email you@example.com
echo 'OPENAI_API_KEY=sk-...' >> .env

# 2. Start the control plane (dev mode auto-runs migrations and reloads on change)
uv run airllmcp serve --dev

# 3. Start the data plane; it polls the bundle and goes ready
uv run airllmdp --dev
```

### Docker Compose

The same stack runs under compose: a one-shot `init` service bootstraps a shared
`state` volume (keys, config, db, bundle cache), then the control plane, data
plane and console start against it. `init` is idempotent, so every `up` re-runs
it and it converges without churning tokens.

```bash
AIRLLM_ADMIN_EMAIL=you@example.com OPENAI_API_KEY=sk-... docker compose up -d --wait

# caller key for requests through the gateway
export AIRLLM_TOKEN=$(docker compose exec data-plane sh -c '. /state/.env && echo $AIRLLM_TOKEN')

# management token to sign in to the console
docker compose exec data-plane sh -c '. /state/.env && echo $GW_ORG_MGMT_TOKEN'
```

Provider keys are passed through the environment (compose also reads them from
`.env` at the repo root); the minted caller and management tokens live in
`/state/.env` on the volume, read through `docker compose exec` as above. The
gateway listens on `localhost:8080`, the control plane API on `localhost:8000`,
and the console on `localhost:3000`. With `AIRLLM_TOKEN` exported, the request
below works without the `source .env` step. `docker compose down -v` resets the
instance.

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
uv run airllm keys list         # every list command takes -f table|json|text
uv run airllm keys create       # flags, or interactive prompts for anything omitted
uv run airllm keys revoke k-... # takes effect at the next compile
uv run airllm bundles compile   # recompile and sign after any change
```

The admin API is browsable at `http://localhost:8000/docs`; authorize with the
`GW_ADMIN_MGMT_TOKEN` from `.env`.

## Configuration

- `airllm.yml` holds all non-secret config for both planes, grouped by domain.
  Secrets are referenced as `env:VAR` entries and resolved from the environment.
- `.env` holds the secrets: the bundle signing key pair, admin and data plane
  bearers, provider API keys. `airllmcp init` maintains it: tokens that are
  still valid against the database are kept, stale or orphaned ones are
  re-minted.
- Precedence: explicit environment variable, then the config file, then defaults.

## Development

```bash
uv run pytest                   # unit tests for all packages
uv run pytest tests/acceptance  # black-box scenarios against real processes
uv run ruff format --check .    # formatting
uv run ruff check .             # lint, including the plane boundary rules
uv run ty check .               # types, whole workspace
uv run lint-imports             # data plane may never import the control plane or a database
./scripts/generate-api-models.sh  # regenerate the CLI's API models from the OpenAPI spec
```

Repo layout: `packages/contract` is the only code both planes share (bundle and
event schemas, signing, tokens). `apps/control-plane`, `apps/data-plane` and
`apps/cli` are uv workspace members; `apps/webapp` is the React console. The full
design spec lives in `notes/PROTOTYPE.md`, and the working rules in `CLAUDE.md`.
