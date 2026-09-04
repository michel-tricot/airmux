# DigitalOcean

Use a Docker Droplet. The Compose overlay adds Caddy for automatic HTTPS to the default stack.
[App Platform does not support persistent volumes](https://docs.digitalocean.com/products/app-platform/details/limits/),
which the gateway needs for its identity and usage outbox.

## Deploy

Create an Ubuntu Docker Droplet with at least 2 GB RAM. Point your domain's DNS record to it and
allow inbound TCP ports 80 and 443. Install Git and Docker Compose 2.24.4+ if needed, then run:

```sh
git clone https://github.com/michel-tricot/airllm.git
cd airllm
cp .env.example .env
```

In `.env`, add `AIRLLM_DOMAIN=llm.example.com` with your domain and set `POSTGRES_PASSWORD`
to a generated URL-safe value, for example the output of `openssl rand -hex 24`.

```sh
docker compose -f docker-compose.yml -f deploy/digitalocean/compose.yml up -d --build --wait
```

Caddy obtains a certificate once DNS and ports 80/443 are reachable. AirLLM's port 8080 stays
private. Complete [first setup](/docs/deployment/index#first-setup) from your computer using
`https://llm.example.com`.

## Update

Check out the intended release and repeat the Compose command. Keep `.env` and the named
volumes for Postgres, AirLLM, and Caddy certificates. Back up the database and application state
before upgrading. Use the same two `-f` arguments for `logs` and `down`.
