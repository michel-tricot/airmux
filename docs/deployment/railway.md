# Railway

Deploy one AirLLM service and one Postgres service. The root
[railway.json](https://github.com/michel-tricot/airllm/blob/main/railway.json) builds the Dockerfile and configures its health check.

1. Create a Railway project and add a Postgres service named `Postgres`
2. Add AirLLM from your repository fork, using the repository root
3. Attach a persistent volume at `/state`
4. Generate a public domain with target port `8080`
5. Set these application variables and deploy

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `GW_CONSOLE_URL` | `https://${{RAILWAY_PUBLIC_DOMAIN}}` |
| `PORT` | `8080` |
| `RAILWAY_RUN_UID` | `0` |
| `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` | `40` |

Use the image's default start command. It prepares the root-owned volume, then runs the
application as UID 10001. Complete [first setup](/docs/deployment/index#first-setup) using the generated domain.
For a custom domain, set `GW_CONSOLE_URL` to its HTTPS origin.

Redeploy the same service and retain its database and volume. Use one application instance;
Railway's [volume restrictions](https://docs.railway.com/volumes/reference) prevent replicas
sharing this disk.

A Railway deploy button requires a published template. After verifying the project, follow
[Railway's template guide](https://docs.railway.com/templates/create) to publish it with these
services, variables, networking, and volume, then use the generated template URL.
