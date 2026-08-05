# Ideas

A parking lot for ideas we have but are not building yet. Not a roadmap and not a spec. When we
defer something worth remembering, it goes here with enough context to pick up later. When we start
building one, move it out of this file and into the code or the spec.

---

## Token counting endpoint

`POST /v1/messages/count_tokens` on the Anthropic ingress. Claude Code calls it to drive its context
meter, so without it the meter is blank. Would return a token estimate for a given request without
calling the provider. The data plane already has tiktoken for metering estimates, so the machinery
is mostly there. Deferred because it is UX polish, not part of the boundary thesis.

## Dedicated writer thread for the event insert

The usage-event insert runs inline on the request hot path (synchronous SQLite write on the event
loop). Measured cost is small at moderate load but the tail blows up under high concurrency: at 4
workers and 128 concurrent, p99 hit ~1s and throughput collapsed as workers serialized on the write
lock. A dedicated writer thread (own connection, fed by an asyncio.Queue, still awaited before
responding) would unblock the event loop while keeping durability. Only worth it if a single instance
is ever run hot; scale-out by instance sidesteps it. See the throughput numbers from the 4-worker run.

## Meter raw auth failures

`denied` events are recorded only for authenticated-but-unauthorized requests (a valid key hitting a
model it cannot use), because those have a key to attribute the event to. Requests that fail auth
outright (bad or missing token) are not metered. If we ever want visibility into rejected traffic at
the edge, we would need a way to record them without a key and without letting unauthenticated
callers write unbounded rows to the outbox.

## End-to-end acceptance for revocation and cancellation

Acceptance criteria #4 (revocation lands within one poll) and #6 (client-cancelled stream emits a
partial `cancelled` event and closes the upstream) are covered by unit tests but have no black-box
scenario in tests/acceptance. Promoting them would exercise the real request path against a running
data plane, like the control-plane-down and event-replay scenarios already do.

## More benchmarks

- Streaming time-to-first-token overhead, the streaming analogue of the non-streaming overhead test
- Throughput under concurrency as a committed benchmark, including the multi-worker regime where the
  shared-db write lock contends
- A persistence-cost benchmark that runs the throughput sweep with the sqlite and devnull backends
  and reports the delta, so the cost of durable metering is tracked over time rather than measured
  by hand

## Retire mint-root-token

`control-plane mint-root-token` is the one remaining manual step between `airllm init` and a serving
stack, and the only reason the console binary mints credentials at all. Ways to remove it:

- Fold it into first-start bootstrap: the control plane already mints the org, data plane, and
  caller tokens on an empty database; it could mint the instance token too and write GW_MGMT_TOKEN
  to the same env file, even when no spec file is present. Launch becomes init, serve, data-plane.
  Cost: a standing root credential is created implicitly rather than by an operator action.
- Derive instance access from key possession instead of a standing token: any CLI command that needs
  instance scope self-mints a short-lived management token from GW_TOKEN_SIGNING_KEY at invocation
  time. No long-lived root token exists to leak or revoke; holding the signing key is already
  equivalent to holding root. The webapp would mint through the CLI or an enrollment step since it
  cannot hold the key.
- One-time enrollment on first boot, the Jenkins pattern: first start prints a single-use code; the
  operator exchanges it for a root token via the API or webapp login. Pairs naturally with
  [service accounts](#service-accounts-as-control-plane-entities), where the exchange creates the
  operator entity.

The second option is the most aligned with how the project already treats the signing key as the
instance root of trust, and it removes a stored secret instead of adding one.

## Finish service accounts

Users exist with a service_account flag, memberships, and token binding, but two pieces remain:
first-start bootstrap still mints the data plane token ownerless instead of creating a service
account (e.g. dataplane@org.local) to hold it, and nothing yet distinguishes the kinds in behavior;
when human login lands, service accounts must be excluded from it, and kind-specific policies
(token TTLs, sync-only permissions narrower than org admin) become possible. If a third principal
kind ever appears, convert the boolean to a kind enum rather than stacking flags.

## Non-sqlite event collection backends

The `EventOutbox` facade makes the collection method pluggable (sqlite, devnull today). Candidates:
push straight to an external telemetry sink, write to a broker for cross-host aggregation, or a
backend that survives sharing a cache dir across hosts (which the sqlite WAL backend cannot, since
WAL does not work over a network filesystem). Each is a new subclass plus one line in build_outbox.

## Trigger-based audit logging

On SQLite, an ORM flush listener (audit.py, gated by AUDITED_DIALECTS) writes before/after AuditLog
rows for @audited tables, attributed via the current_actor contextvar; snapshots exclude the
database-owned tombstone timestamps. When Postgres lands, audit moves to database triggers installed
by migration for each @audited table, serializing OLD/NEW with row_to_json and reading the acting
user from a transaction-local GUC (set_config('app.user_id', ..., true)) set alongside the RLS org
context at transaction start; the listener stays SQLite-only so the two mechanisms never double-write.
Triggers catch every write path including Core upserts like the heartbeat, which the ORM listener
cannot. Keep the @audited registry as the source of truth the trigger DDL is generated from.

## Soft delete on Postgres

Decision (2026-08-05): SQLite hard-deletes, full stop; deleted_at stays null until the Postgres
migration, then soft delete lands as one coordinated change. The blueprint:

- Delete conversion: a versioned BEFORE DELETE trigger (touch_trigger_ddl sibling) that sets
  deleted_at and updated_at to the same instant and suppresses the row deletion (RETURN NULL).
- Read filtering at the session layer: a do_orm_execute listener adds
  with_loader_criteria(Tombstonable, lambda cls: cls.deleted_at.is_(None), include_aliases=True,
  track_closure_variables=False) to every ORM select, so fat-model and hand-written queries are
  both scoped to live rows. Escape hatch: execution_options(include_deleted=True), exposed as a
  find/first parameter for admin and history views. Known edge: identity-map hits in session.get
  bypass the filter within a request.
- Identity: surrogate primary keys everywhere, business identity (org slug, provider name, email,
  (user_id, org_id)) moves to partial unique indexes WHERE deleted_at IS NULL. FKs reference the
  surrogate PK because neither dialect lets an FK target a partial index. This matches the existing
  convention of server-minted ids split from caller-facing names.
- Resurrection disappears as a concept: re-adding a removed membership inserts a fresh row; each
  membership period is its own row and tombstones accumulate as history.
- ApiKey.disabled and MgmtToken.revoked stay distinct from deleted_at: revoked feeds bundle
  revocation lists and remains visible; deleted means gone from view.
- Open policy question: what soft-deleting an org does to its keys, providers, and models
  (cascade, orphan, or forbid).
