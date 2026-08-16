# Ideas

A parking lot for work that is intentionally deferred. This is neither a roadmap nor a record of
features that already shipped. Move an idea out when implementation starts, and delete it when the
current architecture makes it irrelevant.

## Anthropic token counting

Add `POST /v1/messages/count_tokens` to the Anthropic ingress so Claude Code can populate its
context meter without calling a provider. The data plane already estimates tokens for metering,
but this endpoint needs a caller-facing accuracy contract and adapter-wide tests.

## Move SQLite outbox writes off the event loop

`SqliteOutbox.record` commits synchronously on the request path. At moderate load this is cheap,
but concurrent workers serialize on SQLite's write lock and can block the event loop. A dedicated
writer thread with an acknowledged queue would retain durability while isolating that blocking
work. Build it only if committed concurrency benchmarks show that single-host scale-out is not
enough.

## Observe unauthenticated gateway traffic

Usage events can attribute an authorization denial to a valid inference key. Invalid or missing
tokens have no principal, and recording every attempt would let unauthenticated callers create an
unbounded telemetry workload. Add aggregate, rate-limited edge metrics if rejected-traffic
visibility becomes operationally necessary.

## Black-box access-key revocation coverage

The acceptance suite now proves client-disconnect accounting through a running data plane. It does
not yet prove that revoking a control-plane access key stops a running data plane within one bundle
poll. Add that scenario when revocation latency becomes a release-level guarantee.

## Data-plane benchmarks

- Streaming time-to-first-token overhead
- Committed concurrency throughput across worker counts
- SQLite versus dev-null outbox cost, so durable metering overhead is measured continuously

## Additional event outbox backends

`EventOutbox` supports SQLite and dev-null. Future deployments may need a broker, an external
telemetry sink, or storage safe across hosts sharing a network filesystem. Keep the request-path
contract synchronous and local; network delivery belongs in the backend's background exporter.

## Soft delete on Postgres

Deletes remain hard and `deleted_at` remains null until soft delete lands as one coordinated
schema and query change. The blueprint is:

- Add a versioned `BEFORE DELETE` trigger beside the touch and audit triggers. It sets
  `deleted_at` and `updated_at` to the same instant and suppresses the physical delete
- Add session-level live-row filtering with an explicit `include_deleted` escape hatch. Account
  for identity-map hits from `session.get`, which bypass loader criteria inside a transaction
- Give membership tables surrogate primary keys. Move reusable business identities such as
  `(user_id, org_id)` to partial unique indexes where `deleted_at IS NULL`
- Treat re-adding a membership as a new row, preserving each membership period as history
- Keep inference-key and access-key revocation distinct from deletion
- Decide whether deleting an org cascades soft deletion, leaves historical children, or is blocked

This must ship with a new trigger DDL version and a migration. Existing trigger functions are frozen.

## Sign exact bundle bytes

Make `SignedBundle.payload` the serialized string covered by the signature. The control plane would
serialize once, sign those bytes, and store them; the data plane would verify before parsing. This
removes re-serialization from verification and lets a lagging data plane ignore new fields after
signature validation. It is a coordinated contract break and is worth doing before third-party or
non-Python consumers depend on the current shape.

## Session lifecycle hardening

- Expired sessions are inert but remain stored because a failed authenticated request rolls back.
  Add a sweeper if table growth becomes material
- A TLS-terminating proxy that forwards HTTP can cause cookies to be minted without `Secure`.
  Before supporting that deployment, trust forwarded scheme headers from configured proxies or
  derive the flag from a configured public HTTPS origin
- Hosted deployments may eventually delegate session storage and recovery to a managed identity
  product while self-hosted deployments keep local password sessions

## Hosted identity and SSO

Revisit OIDC only when a deployment needs closed signup, email recovery, or enterprise identity.
Use one generic PKCE relying party and model brokers as OIDC issuers rather than adding provider-
specific flows. Test verified-identity resolution without a network, protocol failures against a
small fake IdP, and a few conformance cases against a pinned real IdP such as Dex. Do not restore
the removed implementation from history without a current product requirement.

## Remote data-plane enrollment

Quickstart provisions the first co-located data plane with a service account and an instance-scoped
access key limited to bundle polling, event ingestion, and heartbeat. A second machine should not
reuse that credential or require shared disk access.

Add a short-lived, single-use enrollment code that exchanges for a new service account's limited
access key and the pinned bundle public key. Instance scope should remain the default; organization
scope is optional for a dedicated deployment. The data plane persists the result in a private local
file and uses the ordinary poll, event, and heartbeat APIs afterward. Revoking that one key then
retires one deployment without affecting its peers.

## Audit secret-bearing tables safely

`AuthIdentity` and `AuthSession` are intentionally not audited because the database trigger stores
whole before and after snapshots, which would duplicate password and session-token hashes into the
audit log. Add per-table excluded or redacted columns to a new audit-trigger DDL version before
auditing identity records. Session sliding refresh also needs an explicit actor stamp before its
write.

## A policy language for `evaluate`

Keep hand-written pure Python while policies remain simple. If policies become user-authored or
need decision tables, evaluate a non-Turing-complete language compiled when a bundle is admitted:

- CEL for portable expressions
- GoRules ZEN for JSON decision tables and an editor
- Rego only if policy structure grows enough to justify its runtime and ecosystem cost

The compiled program must stay in memory and evaluation must remain synchronous, pure, and free of
I/O. Do not add an asynchronous loader to the request path.

## Generate CLI operations from OpenAPI

The CLI already consumes generated Pydantic request and response models, while its transport still
constructs paths and payload dictionaries by hand. Generate typed operation functions next, keeping
Typer commands, formatting, device login, keyring profiles, and envelope unwrapping hand-written.
The value is compile-time path and body parity; the cost is generator and template maintenance.

## Provider credential policy

Current behavior is fixed: try credentials in priority order, cascade when a scope has no
credentials, and stop when a populated tier is exhausted. A future policy resource could configure:

- `selection`: failover or per-data-plane round robin
- `on_empty`: deny or cascade
- `on_exhausted`: deny or cascade
- Cooldowns for rejected and rate-limited credentials

Resolve precedence in the compiler and emit one merged policy entry per workspace/provider pair.
The data plane should perform a pure lookup, not merge policy on each request.

## Bind inference keys to credential subsets

Allow an inference key to use only a named subset of a workspace's provider credentials. This lets
one workspace expose separate cost or compliance pools. Implement it as a filter over the candidate
tuple already returned by policy evaluation, after provider credential policy has a stable model.

## Caller-selected provider credential

Optionally let a request select one allowed provider credential by header. This depends on
inference-key credential binding so the header can narrow an allowlist rather than select arbitrary
upstream authority. Every ingress dialect would need an explicit mapping.

## Workspace-specific provider endpoints

Provider credentials are workspace-scoped, but provider base URLs remain instance-global. Azure
OpenAI deployments and workspace-local vLLM instances may need a workspace-specific endpoint.
Model and compile that scope explicitly if the use case appears; do not make the data plane perform
a control-plane lookup.
