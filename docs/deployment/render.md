# Render

[Deploy to Render](https://render.com/deploy?repo=https://github.com/michel-tricot/airllm)

The `render.yaml` Blueprint creates one Docker web service, a persistent disk at `/state`, and
managed Postgres. It uses paid compute and storage; Render displays the cost before creation.

Use the button, or select **New > Blueprint** and connect your fork of the repository.
The Blueprint supplies the internal database URL and sets the public origin from
`RENDER_EXTERNAL_URL`. Provider keys stay local until quickstart stores them through the
management API.

Complete [instance claim](/docs/deployment/index#claim-the-instance) using the generated URL as soon as the
service becomes reachable. Until the first account is created, anyone who can reach the sign-up
page can become the instance owner.
For a custom domain, set `AIRLLM_CONSOLE_URL` to its HTTPS origin and redeploy.

Deploy updates manually from Render, retaining the database and disk. Migrations run during
startup. Keep one application instance; [Render persistent disks](https://render.com/docs/disks)
require downtime during replacement and do not support horizontal scaling.

See the [Blueprint reference](https://render.com/docs/blueprint-spec) for the manifest fields.
