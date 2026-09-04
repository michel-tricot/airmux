# Separate services and gateway replicas

Use the split layout when you need to restart or size the control plane and gateways independently:

```sh
docker compose -f docker-compose.split.yml up -d --build --wait
uv run airllm quickstart --url http://localhost:8080
```

Provider setup and the public URL work exactly as in the [quickstart](../../README.md#quickstart).
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

The default and split layouts are separate installation choices. Switching Compose files does
not migrate application state. For an existing installation, move its credential directories to
the shared volumes and its gateway state to exactly one gateway while the application is stopped.
Retain the database and make a backup before moving state.

## Other infrastructure

The Dockerfile exposes `control-plane`, `data-plane`, and `console` targets as well as
the default `all-in-one` target. Both planes load [the shared configuration](../../deploy/docker/airllm.yml).
The split control plane initializes the database and catalog on startup.

To deploy across hosts, supply shared credential storage that both planes can access, a reachable
Postgres database, and one persistent state directory per gateway. The checked-in split example
uses local shared volumes; it is not a multi-host deployment. Set
`GW_DATAPLANE_CONTROL_PLANE_URL` to the private control-plane address, and protect that connection.

Keep one control plane with this startup configuration. Multiple control-plane replicas also
need coordinated migration/catalog initialization and shared credential storage.
