# AirLLM

One gateway for your LLM applications, across providers. Use OpenAI and Anthropic clients with
OpenAI, Anthropic, Groq, Fireworks, Together, and other compatible providers. AirLLM handles
routing, scoped provider credentials, inference keys, and usage tracking.

[Deployment guides](docs/deployment/index.md) · [Development](docs/development.md) · [Examples](examples)

## Quickstart

You need Docker with Compose 2.24.4+, Python 3.13+, [uv](https://docs.astral.sh/uv/), and a provider API key.

```sh
git clone https://github.com/michel-tricot/airllm.git
cd airllm
cp .env.example .env
uv sync --all-packages --frozen
```

Add at least one provider key to `.env`, then run:

```sh
docker compose up -d --build --wait
uv run airllm quickstart --url http://localhost:8080
```

`quickstart` creates or resumes your owner account, organization, and workspace. It imports
missing provider credentials from `.env`, preserves existing credentials, and prints a new
`AIRLLM_API_KEY` and a working curl command. It reports **Ready** after completing a real
inference request, which uses your provider's API quota.

Every catalog provider uses `<PROVIDER>_API_KEY`: for example, `GROQ_API_KEY`,
`DEEPSEEK_API_KEY`, or `XAI_API_KEY`. See [.env.example](.env.example) for the full list.
You can also manage provider credentials in the console, scoped to an organization or workspace.

Open **[localhost:8080](http://localhost:8080)** for the console. The console, management API,
and inference API share that address. Docker runs one AirLLM container plus Postgres; database
initialization and gateway authentication happen automatically.

`docker compose down` stops the stack and preserves its data. Adding `-v` deletes its volumes.

## Gateway only

For a local gateway without Postgres or the console, use the standalone configuration:

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

Edit [bundle.standalone.yml](bundle.standalone.yml) to change routing. Standalone mode reloads
that bundle, reads provider keys from the environment, and discards usage events. Its built-in
inference key is for local development. Stop the Docker stack first if it occupies port 8080.

## Connect your SDK

Use the inference key printed by `quickstart`. For the OpenAI Python SDK:

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/inf/v1",
    api_key=os.environ["AIRLLM_API_KEY"],
)
response = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "Hello"}],
)
print(response.choices[0].message.content)
```

Anthropic clients can call the same model:

```python
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
    messages=[{"role": "user", "content": "Hello"}],
)
print(message.content[0].text)
```

Choose a catalog model whose provider credential you configured. See [examples](examples) for
streaming, tools, and other integrations.

## Deploy

| Platform | Setup |
| --- | --- |
| [Docker](docs/deployment/docker.md) | One AirLLM container and Postgres |
| [Fly.io](docs/deployment/fly.md) | One app and Machine, plus Managed Postgres |
| [Railway](docs/deployment/railway.md) | Repository service, volume, and Postgres |
| [Render](docs/deployment/render.md) | Deploy button with a checked-in Blueprint |
| [DigitalOcean](docs/deployment/digitalocean.md) | Docker Droplet with automatic HTTPS |

All use the same image. For independent services and multiple gateways, use
[docker-compose.split.yml](docs/deployment/scaling.md).

## Develop

The [development guide](docs/development.md) covers source setup, hot reload, tests, and generated
clients. Docker Compose runs the packaged application; source development runs the Python
services and Vite separately.

The control plane manages configuration in Postgres and publishes bundles to gateways. Gateways
route from their local bundle, stream provider responses, and persist usage for later export.
Separately deployed gateways keep serving during control-plane outages.

Read the [data-plane design](notes/design/DATAPLANE.md), [authority model](notes/design/AUTHORITY.md),
and [credential design](notes/design/BYOK.md). Follow [AGENTS.md](AGENTS.md) when contributing.

AirLLM is pre-1.0. APIs, configuration, and migrations may change before the first stable release.
Licensed under the [Elastic License 2.0](LICENSE).
