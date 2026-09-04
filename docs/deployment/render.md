# Render

The root [`render.yaml`](../../render.yaml) Blueprint creates one Docker web service, a 1 GB
application disk at `/state`, and managed Postgres. The selected compute plans are paid resources.
Review the Blueprint and Render's displayed cost before creating them.

[Deploy to Render](https://render.com/deploy?repo=https://github.com/michel-tricot/airllm)

## Deploy

Use the button, or fork the repository and choose **New > Blueprint** in Render. Connect the fork
and select its root `render.yaml`. Keep the service and database in the same region.

Render provides the private database connection through `DATABASE_URL`. AirLLM reads
`RENDER_EXTERNAL_URL` as the public origin, so no application hostname needs to be guessed before
Render allocates it. The service listens on port 8080.

The start command runs migrations, initializes the catalog and pool key, then starts both planes
and the console. Persistent state is prepared on the mounted disk, and servers run as UID 10001.
Startup health checks call the management API, which does not require an owner account yet.

Open the allocated URL and complete [first setup](index.md#first-setup). When using a custom domain,
set `GW_CONSOLE_URL` to its full HTTPS origin and redeploy.

## Updates

Automatic application deploys are disabled in the Blueprint. After reviewing a release, deploy it
manually from Render, retaining the existing database and disk. Migrations run during startup,
when the disk is available. A failed migration stops startup.

Use one application instance. Render services with attached disks have scaling and deployment
restrictions, including brief downtime during replacement. Back up the disk and database separately.
See [Render persistent disks](https://render.com/docs/disks).

The database has an empty external IP allowlist; the application uses Render's internal network.
For more about the fields and validation, see the
[Blueprint reference](https://render.com/docs/blueprint-spec). The deploy-button flow is described
in [Render's button documentation](https://render.com/docs/deploy-to-render).
