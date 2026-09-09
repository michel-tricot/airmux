# Docker

Run from the repository root with Docker Compose 2.24.4 or newer and
[uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
docker compose up -d --build --wait
uv run --package cli --no-dev --frozen airllm quickstart --url http://localhost:8080
```

Add provider keys to `.env` as shown in the [quickstart](/docs#quickstart). The CLI reads them from
the repository checkout and stores them through the API. The default stack keeps two containers
running: AirLLM and Postgres. Open http://localhost:8080 for the console.

## Ports and HTTPS

To use a different port, set both values in `.env`:

```sh
AIRLLM_PORT=9000
AIRLLM_PUBLIC_URL=http://localhost:9000
```

Start Docker, then pass the same public URL to the CLI:

```sh
uv run --package cli --no-dev --frozen airllm quickstart --url http://localhost:9000
```

For a public deployment, terminate HTTPS at your ingress and set `AIRLLM_PUBLIC_URL` to its
HTTPS origin. Create the first account in the web app or run `quickstart` against that origin as
soon as the application starts. Until then, anyone who can reach the sign-up page can claim the
instance owner role. The
[DigitalOcean guide](/docs/deployment/digitalocean) supplies a Caddy overlay for HTTPS.

After the instance is claimed, add `AIRLLM_PUBLIC_SIGNUP=false` to `.env` and recreate the AirLLM
container to require an administrator-issued invitation for new accounts.

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
