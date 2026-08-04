# airllm

An LLM gateway prototype with a strict control plane / data plane split.

The **control plane** (FastAPI + SQLite) holds orgs, API keys, providers and models,
and compiles them into signed, self-contained policy bundles. The **data plane**
(bare Starlette) serves `POST /v1/chat/completions` using only a bundle it polled
and cached on disk: auth, policy and routing happen with zero I/O on the request
path, and the data plane keeps serving even if the control plane is down.
Caller credentials are Ed25519-signed JWTs; revocation propagates through bundle
recompilation within one poll interval.

## Getting started

You need [uv](https://docs.astral.sh/uv/) and an OpenAI API key.

```bash
uv sync --all-packages

# 1. Generate keys and tokens into .env, and the airllm.yml config if missing
uv run airllm init
echo 'OPENAI_API_KEY=sk-...' >> .env

# 2. Start the control plane (dev mode auto-runs migrations and reloads on change)
uv run control-plane serve --dev

# 3. In another shell: create org, providers, models and a caller key, compile a bundle
uv run airllm bootstrap

# 4. Start the data plane; it polls the bundle and goes ready
uv run data-plane --dev
```

Then make a request through the gateway:

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
```

`bootstrap.yml` ships with a catalog of OpenAI-compatible hosted providers
(openai, anthropic, gemini, xai, deepseek, mistral, groq). A model becomes
callable as soon as its provider's key (for example `GROQ_API_KEY`) is in `.env`.

## Everyday commands

```bash
uv run airllm --help            # commands are grouped: Setup, Resources, Testing
uv run airllm keys list         # every list command takes -f table|json|text
uv run airllm keys create       # flags, or interactive prompts for anything omitted
uv run airllm keys revoke k-... # takes effect at the next compile
uv run airllm bundles compile   # recompile and sign after any change
```

The admin API is browsable at `http://localhost:8000/docs`; authorize with the
`GW_ADMIN_TOKEN` from `.env`.

## Configuration

- `airllm.yml` holds all non-secret config for both planes, grouped by domain.
  Secrets are referenced as `env:VAR` entries and resolved from the environment.
- `.env` holds only secrets: signing keys, admin and data plane bearers, provider
  API keys. `airllm init` maintains it and never overwrites existing tokens.
- Precedence: explicit environment variable, then the config file, then defaults.

## Development

```bash
uv run pytest                   # test suite
uv run ruff format --check .    # formatting
uv run ruff check .             # lint, including the plane boundary rules
uv run ty check packages/contract apps/data-plane
uv run lint-imports             # data plane may never import the control plane or a database
./scripts/generate-api-models.sh  # regenerate the CLI's API models from the OpenAPI spec
```

Repo layout: `packages/contract` is the only code both planes share (bundle and
event schemas, signing, tokens). `apps/control-plane`, `apps/data-plane` and
`apps/cli` are uv workspace members. The full design spec lives in
`notes/PROTOTYPE.md`, and the working rules in `CLAUDE.md`.
