# Distributed deployment

The files in [`deploy/distributed`](../../deploy/distributed) provide strict configurations for separately deployed planes and a two-gateway
Compose reference. The reference runs on one Docker host; it demonstrates replica identity,
independent state, and network-only configuration sharing. Multi-host scheduling and availability
remain the responsibility of your orchestrator.

## Start the reference

Provision an empty external Postgres database reachable from the containers. Generate a pool key
once with `uv run airllmcp bootstrap-keygen --out /path/to/pool.key`. Store it in your platform's
secret manager and inject it as `GW_DATAPLANE_TOKEN` into the control plane and every gateway.
Use the same token on every restart; bootstrap rejects a replacement token after initialization.

From the repository root, with `DATABASE_URL`, `GW_DATAPLANE_TOKEN`, and at least one of
`OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in the environment:

```sh
docker compose -f deploy/distributed/compose.yml up -d --build --wait
```

Set `AIRLLM_PUBLIC_URL` and `AIRLLM_PORT` when the public origin differs from http://localhost:8080.
Create the owner and tenant in the console and register the same provider credential value that
the environment holds. This example uses the existing environment secret store: one value per
provider, shared across tenants. Add other provider environment variables to both planes together.
Rotations require updating and restarting every service that reads that value.

For per-tenant provider keys, use a network-accessible secret store in both plane configurations.
The existing `insecure_database` store is a prototype option and stores values as plaintext in
Postgres; it is not an encrypted vault. A production secret-manager adapter is separate work.
Secret values remain outside bundles. Ordinary management database reads never enter the inference path.

## State and routing

`data-plane-1` and `data-plane-2` each mount their own named volume at `/state/data-plane`. Each
volume holds a persistent instance ID, bundle cache, and SQLite outbox. They share only the pool
credential and provider key values. Restart a replica with the same volume, and drain pending events
before permanently deleting it. Anonymous ephemeral volumes are unsuitable for durable usage tracking.

The two gateways share the `data-plane` network alias. nginx re-resolves that name and routes
requests across the returned addresses. For a multi-host installation, point the proxy at a service
address supplied by your orchestrator and route to replicas passing `/readyz`; preserve SSE and
forward the public scheme. The control plane must be reachable via HTTPS or a protected private network.

The example keeps one control plane. Before adding control-plane replicas, coordinate migration
and catalog jobs, inject the same bootstrap token, and use the same external database and secret
store. Run release jobs once, then roll the service containers. Scaling the gateway does not require
scaling the control plane alongside it.
