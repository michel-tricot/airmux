# AirLLM

One gateway for your LLM applications, across providers. AirLLM connects OpenAI and Anthropic
clients to multiple model providers, with a console for organizations, workspaces, provider
credentials, inference keys, and usage.

[Documentation](docs/index.md) · [Deployment guides](docs/deployment/index.md) · [Development](docs/development.md)

## Quickstart

Install Docker with Compose, then run:

```sh
git clone https://github.com/michel-tricot/airllm.git
cd airllm
docker compose up -d --build --wait
```

Open **[localhost:8080](http://localhost:8080)**. Create your account, an organization, and a
workspace. Add a provider API key and create an inference key. The first account owns the instance;
claim it before making a new installation publicly accessible.

AirLLM initializes its database, model catalog, and gateway credentials automatically. Only port
8080 is public. The console, management API, and inference API share this origin.

Send a request using the inference key you created:

```sh
export AIRLLM_API_KEY='your-inference-key'
curl http://localhost:8080/inf/v1/chat/completions \
  -H "Authorization: Bearer $AIRLLM_API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'x-airllm-dialect: openai_native' \
  -d '{"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":"Say hello"}]} '
```

Use a model from the console's catalog whose provider credential you added. Requests consume your
provider's API quota. Configuration changes reach gateways automatically, usually within five seconds.

Stop with `docker compose down`. Your data stays in Docker volumes. Adding `-v` deletes that data.

### One application container

The default layout runs the console, control plane, and gateway separately, plus Postgres. For
one application container plus Postgres, use:

```sh
docker compose -f docker-compose.compact.yml up -d --build --wait
```

Choose one layout per installation. Both use port 8080 by default, and their state volumes are
separate. The [Docker guide](docs/deployment/docker.md) covers ports, TLS, storage, and upgrades.

### Deploy to a cloud

| Platform | Deployment |
| --- | --- |
| [Fly.io](docs/deployment/fly.md) | One Fly app and Machine, persistent volume, Managed Postgres |
| [Railway](docs/deployment/railway.md) | One application service, volume, and Postgres |
| [Render](docs/deployment/render.md) | Blueprint with one web service, disk, and Postgres |
| [DigitalOcean](docs/deployment/digitalocean.md) | Docker Droplet with Compose and automatic HTTPS |
| [Your own infrastructure](docs/deployment/scaling.md) | Separate services and gateway replicas with independent state |

See the [deployment documentation](docs/deployment/index.md) for setup, deploy-button availability,
and platform constraints. All compact deployments use the same image.

## Connect an SDK

For the OpenAI Python SDK, change the base URL and API key:

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

Anthropic clients can call the same model through their native API:

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

See [examples](examples) for streaming, tools, and other integrations.

## Develop locally

Install Python 3.13+, [uv](https://docs.astral.sh/uv/), [Bun](https://bun.sh/), and Docker.
From the repository root:

```sh
uv sync --all-packages --frozen
bun install --frozen-lockfile
docker compose -f docker-compose.dev.yml up -d --wait
uv run airllmcp bootstrap-keygen
uv run airllmcp migrate
uv run airllmcp taxonomy --file taxonomy/taxonomy.yml
```

Generate the bootstrap key only on the first setup. Start each process in a separate terminal:

```sh
uv run airllmcp serve --dev
```

```sh
uv run airllmdp serve --config airllm.yml
```

```sh
bun run dev
```

Open **[127.0.0.1:5000](http://127.0.0.1:5000)** and complete setup. The Vite development server
proxies both APIs. Production Docker uses port 8080; source development uses 5000 for the console,
8000 for the control plane, and 8080 for the gateway.

The [development guide](docs/development.md) covers tests, generated clients, standalone mode,
configuration, and resetting local state.

## Architecture

The control plane owns management data in Postgres and publishes bundles to the data plane. Each
gateway authenticates and routes from its local bundle, streams provider responses, and exports
usage from a durable local outbox. Cached configuration lets it continue serving during control-plane
outages. Provider credentials resolve through the configured secret store.

One canonical request model connects caller dialects and provider families. Policy and metering
are shared across those translations. See the [data-plane design](notes/design/DATAPLANE.md),
[authority model](notes/design/AUTHORITY.md), and [credential design](notes/design/BYOK.md).

## Contribute

Read [AGENTS.md](AGENTS.md) for repository conventions. Open an
[issue](https://github.com/michel-tricot/airllm/issues) for larger changes, and include behavioral
tests and verification with pull requests.

AirLLM is pre-1.0. APIs, configuration, and migrations can change before the first stable release.
Licensed under the [Elastic License 2.0](LICENSE).
