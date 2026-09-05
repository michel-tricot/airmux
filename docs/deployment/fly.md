# Fly.io

AirLLM runs in one Fly app on one Machine, with a persistent volume and Managed Postgres. Its
deployment file is `deploy/fly/fly.toml`.

## Deploy

Install and authenticate [flyctl](https://fly.io/docs/flyctl/install/).
Before provisioning, choose the region where the application, volume, and database will remain.
Change `primary_region` in `deploy/fly/fly.toml` if you do not want `sjc`, then use the same region
below. Choose an app name and create its resources:

```sh
flyctl launch --config deploy/fly/fly.toml --name my-airllm --no-deploy --no-db
flyctl mpg create --name my-airllm --region sjc
```

Use the cluster ID printed by the second command:

```sh
flyctl mpg attach CLUSTER_ID --app my-airllm --config deploy/fly/fly.toml
```

Attachment sets `DATABASE_URL`. Copy the direct connection URL from the database dashboard's
**Connect** tab and save it for migrations:

```sh
openssl rand -hex 24
flyctl secrets set --app my-airllm --stage \
  DIRECT_DATABASE_URL='postgresql://USER:PASSWORD@direct.CLUSTER.flympg.net/DATABASE' \
  AIRLLM_CLAIM_TOKEN='PASTE_THE_RANDOM_VALUE'
flyctl deploy --config deploy/fly/fly.toml --app my-airllm --ha=false \
  --env AIRLLM_CONSOLE_URL=https://my-airllm.fly.dev
```

Put the same `AIRLLM_CLAIM_TOKEN` in your local `.env`; quickstart sends it only while creating the
first owner.

Keep Managed Postgres in its default session pooling mode. Fly documents the pooled and direct
connections in [Connect your client](https://fly.io/docs/mpg/client-configuration/).
Startup uses the direct URL for migrations and the pooled URL for the application.

Complete [first setup](/docs/deployment/index#first-setup) at `https://my-airllm.fly.dev`.

## Update

Repeat the deploy command with the same app name and origin. Keep `--ha=false`: this layout
owns one `/state` volume and runs one gateway. Use [separate services](/docs/deployment/scaling) for replicas.

For GitHub Actions, set `FLY_API_TOKEN` as a secret and `FLY_APP` as a variable in the
`production` environment, then run the `deploy-fly` workflow. `AIRLLM_PUBLIC_URL` may name an
attached custom domain. Moving regions requires migrating both the Fly volume and database.
