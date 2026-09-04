# Deploy AirLLM

AirLLM supports a compact installation and separate services. Both serve the console at `/`, the
management API at `/api/v1`, and inference at `/inf/v1` on one public origin.

## Choose a platform

| Platform | Included configuration | Persistent storage | Setup |
| --- | --- | --- | --- |
| [Docker](docker.md) | Split and compact Compose files | Docker volumes and Postgres | One Compose command |
| [Fly.io](fly.md) | One app, one Machine, Managed Postgres | `/state` Fly volume | Bootstrap script |
| [Railway](railway.md) | `railway.json` for one application service | `/state` volume and Postgres service | Connect repository and configure resources |
| [Render](render.md) | `render.yaml` Blueprint | `/state` disk and managed Postgres | Deploy to Render button |
| [DigitalOcean](digitalocean.md) | Droplet Compose stack with Caddy | Droplet volumes and Postgres | Docker Droplet plus Compose |
| [Separate services](scaling.md) | Two-gateway Compose reference | One volume per gateway, external Postgres | Operator-managed infrastructure |

Fly, Railway, and Render host the same `all-in-one` Docker target. DigitalOcean runs that target
behind Caddy. Each compact installation has one application instance and a separate database.
Start with this layout if you want the fewest moving parts. Use the separate targets when you need
to size or deploy the planes independently.

## First setup

Open the public URL immediately after deployment. The first signup becomes the instance owner.
Create an organization and workspace, add a provider credential, and mint an inference key. On a
public host, claim the instance before sharing its URL or restrict ingress during setup.

The deployment prepares migrations, the catalog, and gateway authentication. You do not need to
generate provider keys or owner credentials in the platform dashboard.

Verify with [the quickstart request](../../README.md#quickstart), using a configured provider and
model. Then configure backups and monitoring from the [operations guide](operations.md).

## Deploy buttons

[Deploy to Render](https://render.com/deploy?repo=https://github.com/michel-tricot/airllm) consumes
the root Blueprint. The Blueprint requires paid compute and persistent storage; review the
resources before confirming creation.

Railway deploy buttons require a published Railway template ID. The repository includes service
configuration and [template publication instructions](railway.md#publish-a-deploy-template), but
does not invent a template URL before a template has been published in a Railway account.

Fly provides a bootstrap command. DigitalOcean uses a Docker Marketplace Droplet and the checked-in
Compose stack. These are documented setup flows rather than AirLLM marketplace listings.

## Storage and scaling

Compact state includes gateway authentication, provider secrets, cached bundles, the instance ID,
and the usage outbox. Keep `/state` across deployments. Back up the database and state together.
Application disks alone do not back up Postgres.

Never start two gateways against the same state directory or SQLite outbox. A compact installation
is a single-instance deployment; a disk snapshot or clone is not a second gateway identity. The
[scaling guide](scaling.md) covers separate gateway state and shared provider-credential resolution.

## Validation scope

Repository deployment tests run real containers and HTTP requests against a deterministic local
provider. They cover onboarding, inference, streaming, usage delivery, and restart behavior. Cloud
manifests are checked against provider documentation and schemas where available. Account-specific
provisioning, quotas, DNS, and platform routing still need a smoke check after deployment.
