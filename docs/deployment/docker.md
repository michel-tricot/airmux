# Docker

Run from the repository root with Docker Compose 2.24.4 or newer:

```sh
docker compose up -d --build --wait
docker compose run --rm -it setup
```

Add provider keys to `.env` as shown in the [quickstart](/docs#quickstart). The default stack keeps
two containers running: AirLLM and Postgres. `setup` is a one-shot container that receives `.env`,
stores provider keys through the API, and exits. The `-it` flags keep input attached and allocate
the terminal used by the account and password prompts. Open http://localhost:8080 for the console.

## Ports and HTTPS

To use a different port, set both values in `.env` so `up` and the later `setup` command use the
same public origin:

```sh
AIRLLM_PORT=9000
AIRLLM_PUBLIC_URL=http://localhost:9000
```

Then run the two Compose commands from the quickstart. Setup reaches AirLLM over the private Docker
network but saves and prints `AIRLLM_PUBLIC_URL` for clients outside Docker.

For a public deployment, terminate HTTPS at your ingress and set `AIRLLM_PUBLIC_URL` to its
HTTPS origin. Generate `AIRLLM_CLAIM_TOKEN` with `openssl rand -hex 24` before starting the stack.
The application refuses to expose an unclaimed public installation without it. The
[DigitalOcean guide](/docs/deployment/digitalocean) supplies a Caddy overlay for HTTPS.

## State and updates

The `pgdata` volume holds Postgres. The `state` volume holds application credentials, gateway
identity, bundle cache, and pending usage. Preserve both and back them up before updates.
Set a URL-safe `POSTGRES_PASSWORD` in `.env` before creating a public installation.

Check out the intended release and repeat `docker compose up -d --build --wait`.
Startup applies migrations and the shipped model catalog before serving. The image prepares
volume ownership, then runs its servers as UID 10001.

`docker compose down` keeps volumes. `docker compose down -v` deletes the installation.
Changing `POSTGRES_PASSWORD` after initialization does not rotate the database's password.

## Separate services

[docker-compose.split.yml](/docs/deployment/scaling) runs the console, control plane, and two gateways
independently. Both layouts use the same Dockerfile and runtime configuration.

## Verification

CI checks both layouts with a local test provider: account setup, `quickstart`, inference,
streaming, usage export, restarts, and gateway state. To reproduce against a fresh installation:

```sh
AIRLLM_PORT=18080 AIRLLM_PUBLIC_URL=http://localhost:18080 \
  docker compose -p airllm-test up -d --build --wait
AIRLLM_PORT=18080 AIRLLM_PUBLIC_URL=http://localhost:18080 \
  DEPLOYMENT_PROJECT=airllm-test DEPLOYMENT_FILE=docker-compose.yml \
  DEPLOYMENT_URL=http://localhost:18080 \
  uv run pytest tests/deployment
```

The tests create accounts and restart services. Use a disposable installation.
