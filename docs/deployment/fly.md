# Fly.io deployment

AirLLM runs as one Fly app on one Machine using the root Dockerfile's `all-in-one` target. The
Machine runs nginx, the console, the control plane, and the data plane. Managed Postgres remains
separate. nginx exposes port 8080; both planes bind to loopback.

| Public path | Target |
| --- | --- |
| `/api/v1/*` | Control plane on localhost:8000 |
| `/inf/v1/*` | Data plane on localhost:8081 |
| `/readyz` | Gateway bundle readiness |
| Other application paths | React console |

The `/state` volume holds the shared pool credential, provider secrets, and gateway cache/outbox.
It belongs to one Machine. Do not horizontally scale this configuration; use separately deployed
gateways with independent state and a shared secret store for a larger installation.

## Provision

Install and authenticate `flyctl`, then run from the repository root:

```sh
flyctl auth login
./deploy/fly/bootstrap.sh your-installation
```

This creates one app named `your-installation`, a Managed Postgres cluster with the same name,
and the persistent application volume during deployment. The public URL is
`https://your-installation.fly.dev`. The default region is `sjc`, with a Basic 10 GB database.
Bootstrap reuses matching resources after a partial setup.

Open the console to create the owner account, organization, workspace, provider credential, and
inference key. The shared data-plane credential is initialized automatically. CLI setup is also
available with `uv run airllm quickstart --url https://your-installation.fly.dev`.

Select `FLY_ORG` when the account has multiple organizations. You can also override `FLY_REGION`,
`FLY_MPG_PLAN`, `FLY_MPG_VOLUME_SIZE`, and `AIRLLM_PUBLIC_URL`.

## Deploy updates

```sh
FLY_APP=your-installation ./deploy/fly/deploy.sh
AIRLLM_PUBLIC_URL=https://your-installation.fly.dev ./deploy/smoke.sh
```

The Fly release command sets `DATABASE_URL` from the required `DIRECT_DATABASE_URL` for migrations
and uses the shared `deploy/docker/migrate.yml` config without requiring the state volume.
The application uses the pooled `DATABASE_URL`. Both are installed as Fly secrets by bootstrap.
Deployment disables spare high-availability Machines because this layout owns one local volume.
Updates and process failures can interrupt the combined application.

To configure GitHub Actions as well, authenticate `gh` and explicitly supply the repository:

```sh
GH_REPO=owner/repository ./deploy/fly/bootstrap.sh your-installation
```

This adds one app-scoped `FLY_API_TOKEN` and the `FLY_APP`, `FLY_REGION`, and `AIRLLM_PUBLIC_URL`
variables to the `production` GitHub environment. Use the `deploy-fly` workflow's Run workflow
button for subsequent updates. Override `GITHUB_ENVIRONMENT` or `FLY_TOKEN_EXPIRY` during bootstrap
when needed. Existing deploy secrets are preserved. GitHub is optional for local deployments.

For a custom domain, attach it to this app and pass its HTTPS origin as `AIRLLM_PUBLIC_URL` when
deploying. This configuration creates a new installation; it does not move volumes or delete apps
from the earlier two-app layout.
