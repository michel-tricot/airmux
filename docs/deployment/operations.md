# Operations

## Health and first inference

The shared proxy exposes `/healthz` for proxy liveness and `/readyz` for gateway bundle readiness.
The management API exposes `/api/v1/instance/oss/claim`, which is also used for startup checks.
An empty installation can be live before its first usable inference bundle exists.

Run a basic smoke check from a repository checkout:

```sh
AIRLLM_PUBLIC_URL=https://your-domain ./deploy/smoke.sh
```

This checks the console, management API, and the gateway route. The gateway returns 401 for the
invalid token once configured, or 503 before a usable bundle exists. Complete
verification with an authenticated request using a configured provider and model. Add `"stream":true`
and `curl -N` to verify streaming through your platform's edge proxy.

## Persistent state

| Data | Compact location | Backup requirement |
| --- | --- | --- |
| Accounts, sessions, catalog, policies, usage | Postgres | Database-native backup |
| Shared gateway pool key | `/state/runtime` | Preserve with the database |
| Provider credential values | `/state/secrets` | Preserve securely with the database |
| Gateway identity, cached bundles, queued usage | `/state/data-plane` | Preserve for this gateway only |

Split Docker uses separate named volumes for these paths. Each additional gateway has its own
state. Drain its usage outbox before retiring that gateway; deleting the volume discards queued events.
Do not attach a cloned gateway volume to a second running replica.

The default file secret store keeps plaintext credential files readable only by the application
user. Restrict volume and backup access. A database restore without matching secret files leaves
credential references unresolved. The pool key must also match the database's authorized key.

Stop application writers for a consistent filesystem backup and follow the database provider's
backup procedure. Practice restoring the database and matching state to an isolated installation.

## Upgrade

Back up state and Postgres, review release/schema changes, and deploy the selected commit. Retain
persistent mounts and database variables. Split Docker runs one initialization job; compact
managed-platform startup runs migrations before serving; Fly runs migrations as a release command.
Migrations fail startup or deployment if they cannot complete.

The shipped taxonomy is applied during initialization and compact startup. Edits to shipped catalog
entries can be overwritten by the catalog in a new image. Keep intended catalog changes in source.

AirLLM currently maintains a pre-release baseline migration. Do not assume every older development
schema has an in-place upgrade path. Never automatically delete data to recover a failed migration.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Login or CSRF failure | `GW_CONSOLE_URL` must match the browser's exact origin, including scheme and non-default port |
| First inference returns 401/503 | Add provider credentials and an inference key, then allow the bundle poll to complete |
| Gateway works but usage stops appearing | Control-plane reachability, pool credential validity, and free outbox disk space |
| App fails after replacing a disk | Restore the matching pool key and provider-secret files alongside Postgres |
| No output until a stream finishes | Edge/load-balancer buffering and idle timeout; the bundled proxies disable buffering |
| Startup cannot write state | Mount `/state` on compact deployments; let its entrypoint prepare ownership before dropping privileges |
| Port 8080 already in use | Stop the other local layout, or set both `AIRLLM_PORT` and `AIRLLM_PUBLIC_URL` |

The split Compose proxy refreshes backend DNS after replacement. Bundle distribution is eventually
consistent. For orchestrated deployments, admit gateways to the load balancer only once `/readyz`
passes, allow configuration propagation, and provide graceful connection draining.
