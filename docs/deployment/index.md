# Deploy AirLLM

The default deployment runs the console and both planes in one application container, with
Postgres alongside it. Start here unless you need to deploy or scale the planes independently.

| Platform | Configuration |
| --- | --- |
| [Docker](/docs/deployment/docker) | `docker-compose.yml` |
| [Fly.io](/docs/deployment/fly) | `deploy/fly/fly.toml` |
| [Railway](/docs/deployment/railway) | `railway.json` |
| [Render](/docs/deployment/render) | `render.yaml` Blueprint and deploy button |
| [DigitalOcean](/docs/deployment/digitalocean) | Docker Compose with a Caddy overlay |
| [Separate services](/docs/deployment/scaling) | `docker-compose.split.yml`, including two gateways |

## Configure the application

The same Docker image runs on every platform. Each platform guide connects these three things:

| Setting | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres connection string |
| `GW_CONSOLE_URL` | Public origin, such as `https://llm.example.com` |
| Persistent volume at `/state` | Gateway identity, cached bundles, pending usage, and credential files |

The application listens on port 8080. It initializes the database, catalog, and gateway
authentication during startup. The console, management API, and inference API share one origin.

## First setup

From a repository checkout on your computer, install the CLI with
`uv sync --all-packages --frozen`. Copy `.env.example` to `.env` and fill in your provider keys,
then run:

```sh
uv run airllm quickstart --url https://your-airllm-domain
```

Claim a new public installation immediately: the first account becomes its owner.
`quickstart` creates or resumes that account, an organization, and a workspace. It imports
missing provider keys from your local `.env` using `<PROVIDER>_API_KEY` for every catalog provider.
Existing credentials remain intact. Save the inference key it prints; **Ready** means a real
request succeeded through the deployed gateway.

You can also complete setup in the console. Provider credentials added through either interface
are stored in the installation's secret store; setting a platform environment variable alone
does not register a provider credential.

## Keep your data

Retain both Postgres and `/state` on redeployment, and back them up together. The state volume
contains plaintext provider credential files as well as pending usage. Restrict backup access.

The combined image runs one gateway and owns one state volume. Use [separate services](/docs/deployment/scaling)
for multiple gateways, each with its own identity and usage outbox. Updates to the combined
application can briefly interrupt traffic.

Cloud manifests are validated locally; account provisioning and public routing require a check
on the target platform. After deploying, `quickstart` verifies inference through its public URL.
