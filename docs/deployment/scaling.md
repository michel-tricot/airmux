# Separate services and gateway replicas

Use the split layout when you need to restart or size the control plane and gateways independently:

```sh
docker compose -p airllm-split -f docker-compose.split.yml up -d --build --wait
docker compose -p airllm-split -f docker-compose.split.yml run --rm setup
```

Provider setup and the public URL work exactly as in the [quickstart](/docs#quickstart).
This runs Postgres, the console proxy, one control plane, and two gateways on one Docker host.
The proxy distributes inference requests between the gateways.

## State

| Volume | Ownership |
| --- | --- |
| `pgdata` | Postgres |
| `runtime-credentials` | Control plane writes the pool key; gateways read it |
| `provider-secrets` | Control plane writes provider credentials; gateways read them |
| `gateway-1`, `gateway-2` | Each gateway owns its identity, cached bundles, and usage outbox |

The gateways keep serving cached configuration while the control plane is unavailable and
export queued usage when it returns. Restart each gateway with its original volume. Every
additional gateway needs a new volume; cloning a running gateway's identity or sharing its
SQLite outbox is invalid.

The default and split layouts use different database and application volumes. Keep the explicit
`airllm-split` project name in every command. Migrating an existing installation requires a database
dump plus a stopped copy of `/state/runtime`, `/state/secrets`, and one gateway's `/state/data-plane`.
Restore them into the corresponding split volumes before the first split startup.

## Other infrastructure

The Dockerfile exposes `control-plane`, `data-plane`, and `console` targets as well as
the default `all-in-one` target. Both planes load the shared `deploy/docker/airllm.yml` configuration.
The split control plane initializes the database and catalog on startup.

To deploy across hosts, supply shared credential storage that both planes can access, a reachable
Postgres database, and one persistent state directory per gateway. The checked-in split example
uses local shared volumes; it is not a multi-host deployment. Set
`GW_DATAPLANE_CONTROL_PLANE_URL` to the private control-plane address, and protect that connection.

Keep one control plane with this startup configuration. Multiple control-plane replicas also
need coordinated migration/catalog initialization and shared credential storage.
