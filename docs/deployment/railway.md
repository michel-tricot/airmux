# Railway

Deploy one AirLLM service and one Postgres service in the same Railway project. The root
[`railway.json`](../../railway.json) builds the final `all-in-one` target of the root Dockerfile
and runs migrations before starting the application.

## Create the services

1. Create a Railway project and add its Postgres service, named `Postgres`
2. Add AirLLM from your fork of this repository, keeping the repository root as the build context
3. Attach a persistent volume to AirLLM at `/state` before its first successful startup
4. Generate a public domain for AirLLM and set its target port to `8080`
5. Add the application variables below and deploy

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `GW_CONSOLE_URL` | `https://${{RAILWAY_PUBLIC_DOMAIN}}` |
| `PORT` | `8080` |
| `RAILWAY_RUN_UID` | `0` |
| `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` | `40` |

Use Railway's private database URL reference. If you give Postgres a different service name,
update the reference. The image initially prepares ownership on `/state`, then runs all services
as UID 10001. `RAILWAY_RUN_UID=0` allows that preparation on Railway's root-owned volumes; it does
not leave the application servers running as root.

The config file supplies the start command, health check, retry policy, and single replica. Project
resources, networking, volumes, and variables are configured in Railway, because they are not
created by `railway.json`. See [Railway configuration as code](https://docs.railway.com/config-as-code/reference).

Open the domain and complete [first setup](index.md#first-setup). For a custom domain, set
`GW_CONSOLE_URL` to its full HTTPS origin and redeploy.

## Updates and limits

Redeploy the same service with its existing volume and database. Back up both before upgrades.
The attached volume requires a single instance, and deployments can briefly interrupt traffic.
See [Railway volumes](https://docs.railway.com/volumes/reference) for the platform's restrictions.
Do not enable replicas on this compact installation. Use [separate gateways](scaling.md) for a
larger installation, each with its own service and persistent state.

## Publish a deploy template

After verifying an installation in your Railway account, create a template from the project.
Include the AirLLM repository source, Postgres service, private database reference, application
variables, public networking on 8080, and the `/state` volume. Test a fresh installation from that
template, then use the deploy URL Railway generates as the public button link.

This publication step needs a Railway account and produces an account-owned template identifier.
See [Railway's template guide](https://docs.railway.com/templates/create). The repository's config
is ready to use without publishing a template.
