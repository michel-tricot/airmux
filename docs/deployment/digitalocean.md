# DigitalOcean

Use a Docker Droplet with the checked-in [`compose.yml`](../../deploy/digitalocean/compose.yml).
It runs one AirLLM application container, Postgres, and Caddy for automatic HTTPS. Only Caddy
publishes public ports; the application and database communicate over the private Docker network.

DigitalOcean App Platform does not support persistent volumes. Its ephemeral filesystem cannot
preserve AirLLM's provider-secret files or durable usage outbox, so this deployment uses a Droplet.
See [App Platform storage limits](https://docs.digitalocean.com/products/app-platform/details/limits/).

## Create the host

Create a [Docker Marketplace Droplet](https://docs.digitalocean.com/products/marketplace/catalog/docker/)
with an SSH key. Allow enough memory for both the application and source-image build; 4 GB is a
reasonable starting allocation for building on the host. Size it from your own workload after testing.

Point a domain's A record at the Droplet. Add an AAAA record only if the Droplet is reachable over
IPv6. Configure a DigitalOcean Cloud Firewall allowing TCP 80 and 443, optional UDP 443, and SSH
from your administration IP. Keep port 8080 and Postgres private.

## Start AirLLM

SSH to the Droplet and install Git if it is not present. Confirm `docker compose version` works,
then run:

```sh
git clone https://github.com/michel-tricot/airllm.git
cd airllm
umask 077
printf 'AIRLLM_DOMAIN=llm.example.com\nPOSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 24)" > deploy/digitalocean/.env
```

Replace `llm.example.com` with your domain before starting:

```sh
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/compose.yml up -d --build --wait
```

Migrations, gateway credentials, and the catalog initialize automatically. Caddy obtains and
renews a certificate after DNS points at the Droplet and ports 80/443 are reachable. Open
`https://llm.example.com` and complete [first setup](index.md#first-setup). For restricted onboarding,
initially allow HTTPS only from your administration IP.

The `.env` file stays on the host and is ignored by Git. Keep its database password stable across
restarts. The named volumes retain Postgres, AirLLM state, and Caddy certificates.

## Update and operate

Back up Postgres and the state volume before upgrading. Check out the intended release or commit,
then repeat the Compose command above. Read logs with:

```sh
docker compose --env-file deploy/digitalocean/.env -f deploy/digitalocean/compose.yml logs --tail 100
```

`down` stops the stack; `down -v` destroys its volumes. Droplet backups alone may not give a
transactionally consistent database backup, so retain database-native backups too. See the
[operations guide](operations.md).

For larger deployments, use [separate gateways](scaling.md) and an external or managed Postgres
server. An ordinary App Platform deploy button would discard gateway state on replacement, so
this repository does not advertise one for the current storage model.
