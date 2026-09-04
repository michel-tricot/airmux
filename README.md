# AirLLM

**One gateway for your LLM applications, across providers**

AirLLM gives OpenAI and Anthropic clients a stable API while letting you choose where each model
runs. Start with a single process and an API key, then add the control plane, web console,
organizations, workspaces, bring-your-own provider credentials, and durable usage tracking when
you need them.

Provider choice belongs in infrastructure, not throughout application code. AirLLM translates
requests and responses through a canonical model, so an Anthropic client can call an OpenAI-hosted
model and an OpenAI client can call an Anthropic model without provider-specific branches in the
application.

## Why AirLLM

- Use the OpenAI Chat Completions API and Anthropic Messages API through one gateway
- Route models across OpenAI, Anthropic, Groq, Fireworks, Together, and other compatible providers
- Keep provider credentials scoped to an organization or workspace
- Authenticate, route, and enforce policy from a validated local bundle
- Keep serving from cached configuration when the control plane is unavailable
- Capture usage and cost events without making the management database part of the request path
- Run only the data plane for local development or the complete stack for a team

## Try it in two minutes

Standalone mode runs one data-plane process. It needs no Postgres, control plane, or web console.

You need:

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/)
- An OpenAI API key

Clone the repository and start the gateway:

~~~bash
git clone https://github.com/michel-tricot/airllm.git
cd airllm
uv sync --all-packages --frozen

export OPENAI_API_KEY=sk-...
uv run airllmdp serve --config airllm.standalone.yml
~~~

In another terminal:

~~~bash
curl http://127.0.0.1:8080/inf/v1/chat/completions \
  -H "Authorization: Bearer sk-inf-standalone-dev" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5-nano","messages":[{"role":"user","content":"Say hello in one sentence"}]}'
~~~

That is a real request to OpenAI through AirLLM. The standalone configuration reads
`bundle.standalone.yml`, resolves provider keys from the environment, and reloads bundle changes
automatically. Its built-in inference key is for local development only, and usage events are
intentionally discarded.

## Run the complete stack

The complete stack adds Postgres, the control plane, the web console, multi-tenant credentials, and durable usage export.

You need:

- Docker with Compose
- [uv](https://docs.astral.sh/uv/)
- At least one provider API key

Copy the example environment file and replace at least one placeholder with a real provider key,
then start the stack:

~~~bash
git clone https://github.com/michel-tricot/airllm.git
cd airllm

cp .env.example .env

uv sync --all-packages --frozen
docker compose up -d --build
uv run airllm --dev quickstart
~~~

`quickstart` creates or resumes the owner account, personal organization, and default workspace. It
keeps existing credentials, stores missing provider keys from `.env` as global defaults, and mints
a new inference key without replacing earlier keys. Save the `AIRLLM_API_KEY` it prints. The command
reports `Ready` only after that key and a configured catalog model complete a real gateway request.
The stack creates and authorizes its shared data-plane pool key before the control plane reports
healthy. There is no sequential data-plane provisioning step.

The stack is now available at:

- Gateway: [http://localhost:8080](http://localhost:8080)
- Web console: [http://localhost:5000](http://localhost:5000)
- Control-plane API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

Try the managed gateway:

~~~bash
export AIRLLM_API_KEY='the key printed by quickstart'

curl http://localhost:8080/inf/v1/chat/completions \
  -H "Authorization: Bearer $AIRLLM_API_KEY" \
  -H "Content-Type: application/json" \
  -H "x-airllm-dialect: canonical" \
  -d '{"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":[{"type":"text","text":"Why use an LLM gateway?"}]}]}'
~~~

Stop the stack without deleting its state:

~~~bash
docker compose down
~~~

`docker compose down -v` also deletes the database and AirLLM state volumes, so use it only when
you want a clean reset.

### Scale the data plane

Replicas in one gateway pool share one ordinary data-plane access key. Put that token in the
platform's secret store and expose the same value to the control plane and every data-plane replica:

~~~yaml
control_plane:
  bootstrap:
    token: ${env:GW_DATAPLANE_TOKEN}

data_plane:
  bundle:
    kind: remote
    control_plane: &control_plane
      url: https://control-plane.internal
      token: ${env:GW_DATAPLANE_TOKEN}
    cache_dir: .airllm
  events:
    kind: sqlite
    control_plane: *control_plane
    cache_dir: .airllm
~~~

The control plane authorizes the key once; replicas can start, stop, and autoscale independently.
Each replica validates bundles from the authenticated API and keeps them in its local cache. Use
HTTPS or a protected private network between the planes. Rotating or revoking the shared access key
affects the whole pool.

## Use your existing SDK

Point the OpenAI SDK at AirLLM:

~~~python
import os

from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/inf/v1",
    api_key=os.environ["AIRLLM_API_KEY"],
)

response = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello from AirLLM"}],
)

print(response.choices[0].message.content)
~~~

Or point the Anthropic SDK at the same gateway. The model can still be hosted by OpenAI:

~~~python
import os

from anthropic import Anthropic

client = Anthropic(
    base_url="http://localhost:8080",
    api_key="unused",
    auth_token=os.environ["AIRLLM_API_KEY"],
)

message = client.messages.create(
    model="openai/gpt-4o-mini",
    max_tokens=256,
    messages=[{"role": "user", "content": "Hello from AirLLM"}],
)

print(message.content[0].text)
~~~

Streaming, tools, structured provider errors, and cancellation accounting use the same gateway
paths. More runnable examples live in [examples](examples).

## How it works

~~~mermaid
flowchart LR
    Clients["OpenAI and Anthropic clients"] --> DP["Data plane"]
    DP --> Providers["Model providers"]
    Console["Web console and CLI"] --> CP["Control plane"]
    CP -- "policy bundles" --> DP
    DP -- "usage events" --> CP
    CP --> DB[("Postgres")]
~~~

The control plane owns organizations, workspaces, credentials, the model catalog, and bundle
compilation. It publishes self-contained configuration to the data plane over an authenticated
connection. The data plane
uses that local snapshot to authenticate callers, select a model and provider, translate the
request, stream the response, and meter usage. It never queries the control-plane database while
serving an inference request.

Every caller dialect and provider family crosses the same canonical representation. This keeps
policy and metering provider-independent and turns each new integration into one adapter instead
of a matrix of pairwise translators.

Read [the data-plane design](notes/design/DATAPLANE.md) for the request lifecycle, adapter
contracts, streaming behavior, configuration ownership, and failure model. Read
[the authority design](notes/design/AUTHORITY.md) for roles, tenant boundaries, access keys, and
data-plane permissions. Read [the BYOK design](notes/design/BYOK.md) for provider-credential
resolution and isolation.

## Configuration

- `airllm.standalone.yml` runs a local bundle with environment-backed provider secrets and no event export
- `bundle.standalone.yml` is the editable local catalog, policy, and development inference-key bundle
- `airllm.yml` configures the control plane and managed data plane used by Docker Compose
- `deploy/fly` contains the two-image Fly.io deployment and bootstrap guide
- `taxonomy/taxonomy.yml` is the generated provider and model catalog applied by the control plane
- `.env` holds local secrets and is loaded automatically

Do not commit real provider or AirLLM keys. In managed mode, add provider credentials through
`quickstart`, the CLI, or the web console. Configuration changes publish automatically.

## Contributing

Issues, focused pull requests, and new provider or caller adapters are welcome. Before starting a
larger change, open a [GitHub issue](https://github.com/michel-tricot/airllm/issues) so the design
can be discussed early.

Set up the Python workspace:

~~~bash
git clone https://github.com/michel-tricot/airllm.git
cd airllm
uv sync --all-packages --frozen
~~~

Keep changes small, add tests for observable behavior, and run the Python checks:

~~~bash
uv run ruff format .
uv run ruff check .
uv run ty check .
uv run lint-imports
uv run pytest -n auto
~~~

Control-plane unit and architecture tests run without Postgres or Docker. Database-backed tests live separately under `tests/integration`:

~~~bash
uv run pytest apps/control-plane/tests/unit
uv run pytest apps/control-plane/tests/integration -n auto
~~~

Ingress tests separate parsing, dialect resolution, response rendering, stream rendering, and request-path integration. Shared adapter behavior uses registry-parameterized cases. Console tests are grouped by feature, with HTTP fixtures typed against the generated client and wrapped in the API response envelope.

Changes to request handling should also pass the black-box scenarios:

~~~bash
uv run pytest tests/acceptance/scenarios
~~~

For console changes, install [Bun](https://bun.sh/) and run:

~~~bash
bun install --frozen-lockfile
bun run format:check
bun run lint
bun run typecheck
bun run coverage
bun run --filter '@workspace/gateway-console' build
~~~

When an API or canonical schema changes, regenerate the committed clients and schemas instead of editing generated files:

~~~bash
./scripts/export-openapi.sh
./scripts/generate-api-models.sh
./scripts/export-completion-schemas.sh
bun run --cwd lib/api-spec codegen
~~~

A few architectural rules keep the project coherent:

- The data plane never imports the control plane or database frameworks
- `lib/contract` is the only code shared by both planes
- New ingress and egress adapters register through discovery, not a central registry edit
- Data-plane request-path fixes are proven with a real request against a running gateway

See [AGENTS.md](AGENTS.md) for the complete development conventions and boundary rules.

## Repository map

- `apps/data-plane`: inference gateway, adapters, policy evaluation, streaming, and metering
- `apps/control-plane`: management API, catalog, bundle compiler, and event ingestion
- `apps/console`: React management console
- `apps/cli`: setup and resource-management CLI
- `lib/contract`: bundle, event, token, and shared wire contracts
- `model-audit`: provider discovery, behavioral evidence, taxonomy generation, and gateway-gap reporting
- `taxonomy`: generated provider definitions, model catalog, behavioral evidence, and canonical completion schemas
- `tests/acceptance`: black-box gateway scenarios

## Project status

AirLLM is pre-1.0 and under active development. Configuration, migrations, and APIs may change
before the first stable release. Evaluate it carefully before production use.

The first account on a fresh complete-stack deployment becomes the instance owner. Run
`quickstart` and claim the instance before exposing the control plane or console beyond localhost.

## License

AirLLM is licensed under the [Elastic License 2.0](LICENSE) (ELv2).
