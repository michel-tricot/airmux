# Bundle publication

## Problem

Management resources are the source of truth, while data planes serve immutable compiled bundles without reading the
control-plane database. Resource writes must remain fast, survive process loss, and eventually produce a bundle even when a write
bypasses the ORM. Concurrent global and organization changes must not let either change disappear.

## Decision

Postgres owns bundle invalidation. Models that contribute to a bundle declare their scope with `@bundle_input`. The baseline
migration installs a trigger for each declaration. Inserts, deletes, and changes to any column except database-owned timestamps and
explicitly ignored operational fields advance a durable global or organization generation in the same transaction as the resource
write. New columns therefore invalidate by default. A rollback rolls back both.

Global and organization generations are independent. A bundle records the pair it compiled, and an organization's bundle state
records the desired pair, published pair, and current immutable bundle id. Equality of both pairs means current; no ordering exists
between the scopes. Moving a scoped resource dirties both its old and new scope.

The publisher selects a stale organization, takes a transaction-scoped advisory lock, and compiles in a repeatable-read
transaction. It inserts the immutable bundle and updates the current pointer and published pair atomically. A concurrent change is
either visible in that snapshot or leaves its generation stale after publication. Compilation failures retain the current pointer
and retry with bounded backoff.

Management clients do not read generations or publication status. They change resources and assume those changes will be
materialized. Data planes poll a manifest built from current pointers, fetch immutable bundle ids, validate them, and atomically
adopt the complete set.

## Rejected alternatives

- ORM flush listeners miss raw database writes and spread invalidation into transaction teardown and special command paths
- One shared revision ordered across global and organization scopes can lose a later commit when allocation order differs from commit order
- Audit rows are an observability history, not a durable materialization state or consumer-offset protocol
- Compiling in a trigger would put expensive domain work on management transactions and cannot perform asynchronous retries safely
- A separate queue or outbox duplicates state already represented by desired and published generation pairs

## Invariants

- Every committed relevant write advances the affected generation through a database trigger
- Updates to database-owned timestamps and explicitly ignored operational fields do not advance a generation
- A bundle becomes current only with the exact generation pair compiled from its repeatable-read snapshot
- At most one publisher compiles an organization at a time
- Failed or cancelled publication leaves the previous current bundle available
- The manifest contains only current pointers and the bundle fetch path remains immutable
