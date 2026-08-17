# Fly.io MVP deployment

This deployment keeps the repository's two existing images:

- The root backend image runs the control plane and data plane together on one Fly Machine
- The console image runs nginx and the React application in a separate public Fly app

The co-located planes share one persistent `/state` volume. The console reaches both backend ports
through the backend app's private Flycast address.

| Public path | Private target | Target path |
|---|---|---|
| `/api/v1/*` | Backend port 8000 | `/api/v1/*` |
| `/inf/v1/*` | Backend port 8081 | `/inf/v1/*` |
| Everything else | Console nginx | React SPA |

The proxy preserves both API prefixes. The backend generates its bundle signing key pair on the
volume during the first boot. `airllm quickstart` writes the data-plane credential to the same
volume, and the waiting data-plane process then starts automatically. Provider credentials also use
the shared file-backed secret store.

This is intentionally a single-backend-Machine deployment. A Fly Volume can attach to only one
Machine, so the backend cannot scale horizontally without replacing local state with shared storage.

## One-time provisioning

Install `flyctl`, authenticate, and choose globally unique app names and a region:

```sh
export FLY_ORG=your-org
export FLY_REGION=sjc
export FLY_BACKEND_APP=your-airllm-backend
export FLY_CONSOLE_APP=your-airllm
export AIRLLM_PUBLIC_URL="https://${FLY_CONSOLE_APP}.fly.dev"

flyctl apps create "$FLY_BACKEND_APP" --org "$FLY_ORG"
flyctl apps create "$FLY_CONSOLE_APP" --org "$FLY_ORG"
```

Create a Fly Managed Postgres cluster and attach it to the backend app:

```sh
export FLY_MPG_CLUSTER_ID=your-cluster-id
flyctl mpg attach "$FLY_MPG_CLUSTER_ID" --app "$FLY_BACKEND_APP"
```

The attachment installs the pooled `DATABASE_URL`. Copy the direct connection URL from the Managed
Postgres Connect page and add it for migrations:

```sh
flyctl secrets set --app "$FLY_BACKEND_APP" DIRECT_DATABASE_URL='postgresql://user:password@direct.cluster.internal/database'
```

Deploy both apps. The checked-in backend configuration creates a 1 GB volume named `airllm_state`
on the first deployment:

```sh
./deploy/fly/deploy.sh
```

Set up the first account, workspace, data-plane credential, provider credentials, and inference key:

```sh
uv run airllm quickstart \
  --control-plane-url "$AIRLLM_PUBLIC_URL" \
  --console-url "$AIRLLM_PUBLIC_URL" \
  --gateway-url "$AIRLLM_PUBLIC_URL"
```

No token copying or backend restart is required. Verify both routed services:

```sh
curl "$AIRLLM_PUBLIC_URL/api/v1/instance/oss/claim"
curl -i -X POST "$AIRLLM_PUBLIC_URL/inf/v1/chat/completions" \
  -H 'Authorization: Bearer invalid' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

The second request should reach the data plane and return `401 Unauthorized`.

## Subsequent deployments

With the app and region variables still set:

```sh
./deploy/fly/deploy.sh
```

For GitHub Actions, create a `production` environment with these variables:

- `FLY_BACKEND_APP`
- `FLY_CONSOLE_APP`
- `FLY_REGION`
- `AIRLLM_PUBLIC_URL`, optional when using the console app's `fly.dev` URL

Create one app-scoped deploy token for each app as `FLY_BACKEND_API_TOKEN` and
`FLY_CONSOLE_API_TOKEN`. The `deploy-fly` workflow remains manual until initial provisioning is
complete.

## Custom domain

Attach the domain only to the console app, set its public origin, and deploy normally:

```sh
export AIRLLM_PUBLIC_URL=https://airllm.example.com
./deploy/fly/deploy.sh
```
