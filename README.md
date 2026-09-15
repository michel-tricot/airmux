<div align="center">
  <h1>TokKeeper</h1>
  <p><strong>One self-hosted LLM gateway. Any compatible client. Multiple providers.</strong></p>
  <p>
    Connect through a supported inference API while TokKeeper centralizes provider translation, routing, policy,
    credentials, failover, and usage accounting behind one endpoint.
  </p>
  <p>
    <a href="https://github.com/michel-tricot/tokkeeper/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/michel-tricot/tokkeeper/actions/workflows/ci.yml/badge.svg"></a>
    <a href="https://pypi.org/project/tokkeeper/"><img alt="PyPI" src="https://img.shields.io/pypi/v/tokkeeper?logo=pypi&logoColor=white"></a>
    <a href="https://www.python.org/downloads/"><img alt="Python 3.13+" src="https://img.shields.io/badge/python-3.13%2B-3776AB?logo=python&logoColor=white"></a>
    <a href="LICENSE"><img alt="Elastic License 2.0" src="https://img.shields.io/badge/license-Elastic--2.0-4C1?logo=elastic&logoColor=white"></a>
  </p>
  <p>
    <a href="#quickstart">Quickstart</a> ·
    <a href="docs/index.mdx">Documentation</a> ·
    <a href="CONTRIBUTING.md">Contributing</a> ·
    <a href="https://github.com/michel-tricot/tokkeeper/issues/new">Report a bug</a>
  </p>
</div>

TokKeeper gives applications, agents, CLIs, and services one self-hosted origin for calling multiple provider families.
Clients can send Chat Completions, Responses, Messages, or canonical requests through any SDK or integration that can
target the corresponding HTTP API. TokKeeper authenticates the workspace, applies policy, selects a model and scoped
provider credential, translates the request, and records the result.

## Quickstart

Run a local gateway with no Docker, Postgres, or control plane. You need Python 3.13+, [uv](https://docs.astral.sh/uv/),
and an OpenAI API key.

### 1. Install and start the gateway

```bash
uv tool install tokkeeper
mkdir tokkeeper-demo
cd tokkeeper-demo
export OPENAI_API_KEY='your-provider-key'
tokkeeper gateway init
tokkeeper gateway serve
```

`init` creates a local configuration, a model taxonomy, and a private inference key under `.tokkeeper/`. The gateway
reads provider credentials from the environment and reloads taxonomy edits while it runs.

### 2. Make a real model request

In another terminal:

```bash
cd tokkeeper-demo
export TOKKEEPER_INFERENCE_KEY="$(cat .tokkeeper/inference.key)"
curl --fail-with-body http://127.0.0.1:8080/inf/v1/chat/completions \
  -H "Authorization: Bearer $TOKKEEPER_INFERENCE_KEY" \
  -H 'Content-Type: application/json' \
  -H 'X-Tokkeeper-Dialect: openai_native' \
  -d '{"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":"Reply with exactly: tokkeeper ready"}]}'
```

The same gateway accepts streaming requests, tool calls, structured output, reasoning, images, and PDF inputs when the
selected model supports them. Continue with the [gateway-only guide](docs/deployment/gateway.mdx) for configuration and
operation.

## Use your existing client

Any client that can target one of TokKeeper's exposed HTTP APIs and send a bearer token can connect. That includes SDKs,
agent frameworks, CLIs, services, and raw HTTP integrations.

| API | Endpoint |
| --- | --- |
| Chat Completions | `POST /inf/v1/chat/completions` |
| Responses | `POST /inf/v1/responses` |
| Messages | `POST /inf/v1/messages` |
| Canonical | `POST /inf/v1/chat/completions` with `x-tokkeeper-dialect: canonical` |

The OpenAI SDK is one example. Point it at `/inf/v1` and replace the upstream key with a TokKeeper inference key:

```python
import os

from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8080/inf/v1",
    api_key=os.environ["TOKKEEPER_INFERENCE_KEY"],
)

response = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "Why use an LLM gateway?"}],
)

print(response.choices[0].message.content)
```

The client protocol does not constrain the provider route. A Messages request can target an OpenAI-compatible model,
and a Chat Completions request can target an Anthropic model. TokKeeper translates the request and returns the response
and errors in the caller's dialect. See the [OpenAI SDK](docs/guides/openai-sdk.mdx) and
[Anthropic SDK](docs/guides/anthropic-sdk.mdx) guides for complete examples, including streaming.

## Why TokKeeper

- **Protocol-first clients:** connect any SDK, agent framework, CLI, service, or raw HTTP integration that speaks an exposed API
- **Policy at the gateway:** compose model and provider allowlists, price ceilings, request limits, credential rules, denials, strict parameters, and fallbacks
- **Scoped provider secrets:** separate instance, organization, and workspace credentials without exposing secret values to configuration bundles
- **Predictable failover:** retry eligible credentials and route to bounded backup models without escaping workspace policy
- **Complete request records:** capture tokens, cost, latency, status, credential scope, configuration version, and every fallback attempt
- **A resilient request path:** gateways evaluate immutable local bundles and can keep serving through a control-plane outage

The shipped catalog includes Anthropic, Cerebras, DeepSeek, Fireworks, Groq, Mistral, OpenAI, Together, and xAI. Model
IDs, prices, context windows, modalities, capabilities, and parameter support are explicit, inspectable data in the
[taxonomy](taxonomy/taxonomy.yml).

## Full-platform quickstart

Use the complete stack when you want the web console, organizations and workspaces, managed credentials, live policy,
usage history, and audit activity. You need Docker with Compose 2.24.4+, Python 3.13+, uv, and at least one provider API
key.

```bash
git clone https://github.com/michel-tricot/tokkeeper.git
cd tokkeeper
cp .env.example .env
```

Add a provider key such as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` to `.env`, then run:

```bash
uv tool install tokkeeper
docker compose up -d --build --wait
tokkeeper quickstart --url http://localhost:8080
```

`quickstart` creates or resumes the owner account, organization, and workspace; imports missing provider credentials;
mints an inference key; and proves the installation with a real model request. Open
[localhost:8080](http://localhost:8080) for the console.

| Goal | Command |
| --- | --- |
| List catalog models | `tokkeeper models list` |
| Inspect the installation | `tokkeeper doctor` |
| Follow gateway activity | `tokkeeper events tail --interval 2 --keep 30` |
| Follow service logs | `docker compose logs -f tokkeeper` |
| Stop while preserving state | `docker compose down` |

## Architecture

TokKeeper separates mutable management work from the inference request path.

```mermaid
flowchart LR
  A[Application] -->|Inference key| G[Data plane]
  U[Operator] --> C[Console or CLI]
  C --> M[Control plane]
  M --> P[(Postgres)]
  M --> S[(Secret store)]
  M -->|Versioned bundles| G
  G -->|Cold secret resolution| S
  G -->|Provider request| L[LLM provider]
  G -->|Usage and health| M
```

Caller dialects and provider protocols cross through one canonical model. Adding a caller dialect requires one ingress
adapter; adding a provider family requires one egress adapter. Policy, routing, streaming, and metering stay
provider-neutral instead of multiplying into a translator for every caller and provider pair.

The control plane compiles complete, versioned organization bundles. Data-plane workers validate them, build immutable
indexes, and atomically adopt them. Inference therefore avoids management database reads and an in-flight request never
observes partially updated policy. Cold provider-secret resolution is the only database-capable exception, and secret
values never enter a bundle.

Read the [architecture guide](docs/concepts/architecture.mdx) for the full data flow, failure boundaries, and deployment
shapes.

## Documentation

| I want to... | Start here |
| --- | --- |
| Try the complete stack | [Quickstart](docs/quickstart.mdx) |
| Connect an application | [OpenAI SDK](docs/guides/openai-sdk.mdx) or [Anthropic SDK](docs/guides/anthropic-sdk.mdx) |
| Add routing and access rules | [Policy workflow](docs/guides/policy-workflow.mdx) |
| Understand supported inference shapes | [Inference reference](docs/reference/inference.mdx) |
| Deploy TokKeeper | [Deployment overview](docs/deployment/index.mdx) |
| Call the management API | [Management API](docs/reference/management-api.mdx) |
| Work on the project | [Development guide](docs/development.mdx) |

The complete management API is generated from [`lib/api-spec/openapi.yaml`](lib/api-spec/openapi.yaml).

## Contributing and support

Contributions are welcome. Read [Contributing](CONTRIBUTING.md) for the development workflow, architectural boundaries,
generated contracts, and validation expectations. Significant design changes should update the relevant record in
[`notes/design`](notes/design/README.md).

Use [GitHub Issues](https://github.com/michel-tricot/tokkeeper/issues) to report a bug or propose a focused feature.

## License and project status

TokKeeper is pre-1.0. APIs, configuration, and migrations may change before the first stable release. The project is
licensed under the [Elastic License 2.0](LICENSE).
