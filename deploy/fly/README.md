# Fly.io MVP deployment

This deployment keeps the repository's two existing images:

- The root backend image runs the control plane and data plane together on one Fly Machine
- The console image runs nginx and the React application in a separate public Fly app

The co-located planes share one persistent `/state` volume. The console reaches both backend ports
through the backend app's private Flycast address.

| Public path     | Private target    | Target path |
| --------------- | ----------------- | ----------- |
| `/api/v1/*`     | Backend port 8000 | `/api/v1/*` |
| `/inf/v1/*`     | Backend port 8081 | `/inf/v1/*` |
| Everything else | Console nginx     | React SPA   |

The proxy preserves both API prefixes. On first boot, the backend generates one data-plane pool key
on the volume. Control-plane startup authorizes that pool key before the
data plane starts. Provider credentials also use the shared file-backed secret store.

This is intentionally a single-backend-Machine deployment. A Fly Volume can attach to only one
Machine, so the backend cannot scale horizontally without replacing local state with shared storage.

## One-time provisioning

Install `flyctl` and `gh`, authenticate both CLIs, and run bootstrap with the public installation name:

```sh
flyctl auth login
gh auth login
./deploy/fly/bootstrap.sh airllm
```

The name `airllm` derives every resource and setting:

- Backend Fly app: `airllm-backend`
- Frontend Fly app: `airllm-frontend`
- Managed Postgres cluster: `airllm`
- Public URL: `https://airllm-frontend.fly.dev`
- GitHub deployment environment: `production`

Bootstrap creates missing apps and a Basic 10 GB Managed Postgres cluster in `sjc`, attaches the
database, installs its pooled and direct URLs as Fly secrets, creates missing app-scoped GitHub
deploy tokens, writes the GitHub environment variables, and deploys both apps. It reuses matching
resources and secrets on later runs, so the same command is safe to run again after a partial setup.

Accounts with more than one Fly organization must select one explicitly. The region, Postgres plan
and disk size, public URL, GitHub repository and environment, and deploy-token expiry can also be
overridden:

```sh
FLY_ORG=your-org \
FLY_REGION=iad \
FLY_MPG_PLAN=Starter \
FLY_MPG_VOLUME_SIZE=20 \
GH_REPO=owner/repository \
GITHUB_ENVIRONMENT=production \
FLY_TOKEN_EXPIRY=8760h \
./deploy/fly/bootstrap.sh airllm
```

Existing GitHub deploy secrets are preserved instead of generating additional Fly tokens on every
run.

Set up the first account, workspace, provider credentials, and inference key:

```sh
uv run airllm quickstart \
  --url "$AIRLLM_PUBLIC_URL"
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

Use the `deploy-fly` workflow's **Run workflow** button in GitHub Actions. The local deployment script
is also available when the app variables are set. The workflow runs the same script and then checks
the public console, control-plane, and gateway routes:

```sh
export FLY_BACKEND_APP=airllm-backend
export FLY_CONSOLE_APP=airllm-frontend
export FLY_REGION=sjc
./deploy/fly/deploy.sh
AIRLLM_PUBLIC_URL=https://airllm-frontend.fly.dev ./deploy/fly/smoke.sh
```

## Custom domain

Attach the domain only to the console app, set its public origin, and deploy normally:

```sh
export AIRLLM_PUBLIC_URL=https://airllm.example.com
./deploy/fly/deploy.sh
```
