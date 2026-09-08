# Deploy AirLLM

The default deployment runs the console and both planes in one application container, with
Postgres alongside it. Start here unless you need to deploy or scale the planes independently.

| Platform | Configuration |
| --- | --- |
| [Docker](/docs/deployment/docker) | `docker-compose.yml` |
| [Fly.io](/docs/deployment/fly) | `deploy/fly/fly.toml` |
| [Render](/docs/deployment/render) | `render.yaml` Blueprint and deploy button |
| [DigitalOcean](/docs/deployment/digitalocean) | Docker Compose with a Caddy overlay |
| [Separate services](/docs/deployment/scaling) | `docker-compose.split.yml`, including two gateways |

## Configure the application

The same Docker image runs on every platform. Each platform guide connects these three things:

| Setting | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres connection string |
| `AIRLLM_CONSOLE_URL` | Public origin, such as `https://llm.example.com` |
| Persistent volume at `/state` | Gateway identity, cached bundles, pending usage, and credential files |

The application listens on port 8080. It initializes the database, catalog, and gateway
authentication during startup. The console, management API, and inference API share one origin.

## Claim the instance

Claim a new instance as soon as it becomes reachable. Open its web app and create the first account,
or run the CLI command below. The first human account becomes the instance owner. Until that account
exists, anyone who can reach the sign-up page can claim the instance.

For the CLI, add the provider keys you want AirLLM to store to your local `.env`. From a repository
checkout with Python 3.13+ and uv, run:

```sh
uv run --package cli --no-dev --frozen airllm quickstart --url https://your-airllm-domain
```

`quickstart` creates or resumes that account, an organization, and a workspace. It imports
missing provider keys from your local `.env` using `<PROVIDER>_API_KEY` for every catalog provider.
Existing credentials remain intact. Save the inference key it prints; **Ready** means a real
request succeeded through the deployed gateway.

Provider credentials added through the CLI or console are stored in the installation's secret
store. Setting a provider key as a long-running platform environment variable does not register it.

## Keep your data

Retain both Postgres and `/state` on redeployment, and back them up together. The state volume
contains plaintext provider credential files as well as pending usage. Restrict backup access.

The combined image runs one gateway and owns one state volume. Use [separate services](/docs/deployment/scaling)
for multiple gateways, each with its own identity and usage outbox. Updates to the combined
application can briefly interrupt traffic.

The repository checks manifest syntax and runs the shared image under Docker. Platform accounts,
managed databases, and public routing still need verification in your own account. `quickstart`
proves the final public path with a real inference request.
