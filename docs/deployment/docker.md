# Docker deployment

Run commands from the repository root. The default installation is:

```sh
docker compose up -d --build --wait
```

Open http://localhost:8080 and create the first account, organization, workspace, provider
credential, and inference key. The first human account becomes the owner. Initialization generates
a unique gateway pool token and installs the catalog; control-plane startup authorizes that token.
No CLI or provider credential is required to reach the console.

Only port 8080 is public. `/api/v1/` reaches the control plane, `/inf/v1/` reaches the gateway, and
other application paths serve the console. `/healthz` checks the proxy; `/readyz` checks gateway
bundle readiness and returns 503 until an organization has a published bundle. The proxy refreshes
backend DNS, disables streaming buffering, and allows up to 300 seconds between upstream reads.

Set `AIRLLM_PORT=9000` and `AIRLLM_PUBLIC_URL=http://localhost:9000` together to use another port.
For HTTPS, terminate TLS at your ingress and set `AIRLLM_PUBLIC_URL` to that HTTPS origin. nginx
passes the configured scheme to the private control plane, so session cookies receive `Secure`.
The control plane trusts forwarded headers only within this private container network.

## Layouts and image targets

| Configuration | Running application services | Database |
| --- | --- | --- |
| `docker-compose.yml` | Console, control plane, data plane | Local Postgres |
| `docker-compose.compact.yml` | One combined application container | Local Postgres |
| `deploy/distributed/compose.yml` | Console, control plane, two gateway replicas | External Postgres |
| `deploy/fly/fly.toml` | One Fly app and Machine | Fly Managed Postgres |

The root Dockerfile shares backend and frontend build stages. Build a specific runtime with
`docker build --target control-plane .`, `--target data-plane`, `--target console`, or
`--target all-in-one`. The two Python service targets share the backend dependency environment and
start only their own plane. Only the console and combined targets contain the compiled frontend.
Application services run as UID/GID 10001. The combined entrypoint briefly starts as root to prepare a fresh mounted volume, then drops privileges. Node and Bun are used only during the console build.

The compact layout uses the same combined image as Fly:

```sh
docker compose -f docker-compose.compact.yml up -d --build --wait
```

Its launcher supervises all three child processes under tini, forwards termination signals, and
exits unsuccessfully if a child dies, allowing the platform to restart the container. Consequently,
a control-plane process failure restarts the combined application. Use the split layout to keep
inference available during control-plane maintenance.

## Persistent state

| Volume in the split installation | Mounted by |
| --- | --- |
| `pgdata` | Postgres |
| `runtime-credentials` | Initializer writes; both planes read only |
| `provider-secrets` | Control plane writes; data plane reads only |
| `gateway-state` | One data plane, containing its identity, bundle cache, and SQLite usage outbox |

The compact installation stores the three application directories under one `/state` volume.
Back up the database and application volumes together. Provider secret files are owner-readable
plaintext; use storage encryption and restrict access to backups. Supplied bind mounts must be
writable by UID/GID 10001 where the service writes state.

The default database password is for the private local Compose network. Set `POSTGRES_PASSWORD`
for a new installation; use a URL-safe value because Compose also interpolates it into the connection
URL. Changing that variable does not rotate a password in an existing Postgres volume.

The layouts use different volume names and are separate installations. Switching layouts does not
copy data. Do not use `--scale data-plane` with the default file: that would share one identity and
outbox among replicas. Use the [distributed example](scaling.md) for replica-owned state.

## Upgrades and shutdown

After selecting a release, rebuild and redeploy using the same Compose file and project name:

```sh
docker compose up -d --build --wait
```

The initializer runs migrations and catalog installation before the new control plane starts.
The compact layout migrates during startup before any application server runs. These single-host examples allow maintenance
downtime; they do not coordinate a zero-downtime rollout across replicas. For distributed releases,
run migrations once before rolling services and keep each gateway volume attached to its replica.

`docker compose down` preserves named volumes. Adding `-v` deletes the database, credentials,
and pending usage. Draining or preserving the outbox is required before permanently removing a gateway.

`docker-compose.dev.yml` remains the dependencies-only development configuration.

## Verification

The deployment test uses a local HTTP upstream, real control and data planes, and the public proxy.
It verifies signup, enrollment, credentials, inference, unbuffered SSE, usage delivery, restart
persistence, and continued inference while the split control plane is stopped. Run against a fresh
installation, with a unique project name and port:

```sh
AIRLLM_PORT=18080 AIRLLM_PUBLIC_URL=http://localhost:18080 \
  docker compose -p airllm-test up -d --build --wait
DEPLOYMENT_PROJECT=airllm-test DEPLOYMENT_FILE=docker-compose.yml \
  DEPLOYMENT_URL=http://localhost:18080 AIRLLM_PORT=18080 \
  AIRLLM_PUBLIC_URL=http://localhost:18080 uv run pytest tests/deployment
```

Use `docker-compose.compact.yml` for the same checks against the combined image. The test creates
an owner and test resources and restarts application services, so use a disposable installation.
