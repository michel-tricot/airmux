# Railway

[Deploy on Railway](https://railway.com/new/template/UJEw1v) to create one AirLLM service, managed
Postgres, and a persistent volume mounted at `/state`. Railway shows the estimated cost before
creation.

The template builds the repository's `Dockerfile`, exposes port 8080 through a generated HTTPS
domain, and checks `/healthz` before routing traffic. `DATABASE_URL` uses Railway's private network.
Provider keys stay local until quickstart stores them through the management API.

Complete [instance claim](/docs/deployment/index#claim-the-instance) using the generated URL as soon
as the service becomes reachable. Until the first account is created, anyone who can reach the
sign-up page can become the instance owner.

For a custom domain, add it under the AirLLM service's public networking settings, set
`AIRLLM_CONSOLE_URL` to its HTTPS origin, and redeploy.

Keep one AirLLM replica because its `/state` volume can attach to only one deployment. Railway
redeploys the service when `main` changes. Migrations run during startup, and updates can briefly
interrupt traffic.

The complete project definition is in [`.railway/railway.ts`](/.railway/railway.ts). Use Railway CLI
5.42.1 or newer to inspect or apply it:

```sh
railway link
railway config plan
railway config apply
```

See the [Railway Infrastructure as Code reference](https://docs.railway.com/infrastructure-as-code/reference)
for the manifest fields.
