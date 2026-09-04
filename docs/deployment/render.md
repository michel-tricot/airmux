# Render

[Deploy to Render](https://render.com/deploy?repo=https://github.com/michel-tricot/airllm)

The [render.yaml](../../render.yaml) Blueprint creates one Docker web service, a persistent
disk at `/state`, and managed Postgres. It uses paid compute and storage; Render displays the
cost before creation.

Use the button, or select **New > Blueprint** and connect your fork of the repository.
The Blueprint supplies the internal database URL and sets the public origin from
`RENDER_EXTERNAL_URL`. No provider keys are required to start the application.

Complete [first setup](index.md#first-setup) using the generated URL.
For a custom domain, set `GW_CONSOLE_URL` to its HTTPS origin and redeploy.

Deploy updates manually from Render, retaining the database and disk. Migrations run during
startup. Keep one application instance; [Render persistent disks](https://render.com/docs/disks)
require downtime during replacement and do not support horizontal scaling.

See the [Blueprint reference](https://render.com/docs/blueprint-spec) for the manifest fields.
