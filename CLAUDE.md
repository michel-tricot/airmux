# airllm gateway prototype

## Boundary rules, non-negotiable
- data_plane may never import sqlalchemy, sqlmodel, asyncpg, alembic, fastapi, or control_plane.
- The only shared import between planes is contract.
- If a feature seems to need a DB read on the request path, add a field to the bundle instead. Say so before doing it.
- evaluate() must stay pure: no async, no network, no I/O, no datetime.now(). Under 100 lines.

## Adding an adapter
One new module under apps/data-plane/src/data_plane/adapters/. Subclass ProviderAdapter, set `kind`,
implement the eight methods. Touch no other file. If you think you need to edit a registry, the registry
is wrong; fix the registry.

- The transport never parses SSE. frame() owns wire framing and the partial-line buffer.
- StreamState is adapter-shaped. Construct it in new_stream_state(), never in the transport.
- finalize(state) must return a valid CanonicalResponse at ANY point in the stream, including
  after a client disconnect. Cancellation accounting depends on this.
- frame() and transform_stream_event() stay synchronous so the streaming path is testable as a
  pure fold over a recorded byte log.

## Control plane data access
- All DB access goes through the fat-model API on control_plane.models: Record.get/find/first/save/delete, OrgOwned.owned_by, Identified.find_by_id.
- The session is ambient (ContextVar in control_plane.db). One transaction per request, committed at request end; save() flushes, never commits.
- Routes take no SessionDep unless they need raw SQL. Raw sessions are only for what the model API cannot express:
  aggregates, dialect-specific atomic upserts. Do not grow Record into a query builder to absorb them.
- Org-scoped lookups go through owned_by, never a hand-rolled org_id check. NotOwnedError maps to 404 in app.py.
- Non-request code (lifespan, CLI, background tasks) opens its own transaction(); never let a spawned task inherit a request session.
- @audited marks tables for audit coverage; the registry is the source the audit trigger DDL is generated from.
  Database triggers (audit_trigger_ddl_v1, versioned and installed by the migrations like the touch
  triggers) write before/after AuditLog rows for every write path including Core statements, excluding the
  database-owned timestamps. The acting user reaches the triggers through the transaction-local app.user_id GUC.
  Stamping lives in deps (management_claims and acting_user call set_actor); the only route-level stamps are
  account creation (signup) where the user exists only mid-handler, and setup/CLI steps stamp the admin.
  The trigger rejects writes with no stamped actor, so an audited write can never land unattributed; the stamp dies
  with the transaction, so every unit of work attributes explicitly. Never write AuditLog rows by hand.
- Server-minted ids are UUIDv7: take the Identified mixin, which brings the pk (client-side contract.uuid7 so the id
  exists before the first flush, native uuidv7() server default as the backstop), its api_readonly policy, and
  find_by_id. Never declare an id on an Identified model. The data plane mints its ids (event_id, request_id,
  instance_id) through contract.uuid7 too. Org, provider, and model are Identified with the caller-facing identifier
  in `name` (unique for provider and model as catalog keys, free-form for org); bundles and events reference orgs by
  id and providers/models by name. audit_log keeps an integer sequence because uuid7 cannot totally order rows within
  one millisecond; Bundle passes its id explicitly because it is signed into the payload.
- Models list Record first, then capability mixins: Identified, OrgOwned, Tombstonable, future ones. Mixins are plain SQLModel classes
  and never subclass Record; they live in models/common.
- Tombstonable provides created_at, updated_at, and deleted_at. The database owns the values through touch triggers installed
  by the migrations; the ORM never maintains them. updated_at is never null: it equals created_at on creation
  and refreshes on every update. deleted_at stays null for now: deletes are hard until trigger-based soft delete lands
  (blueprint in notes/IDEAS.md). Never declare those fields on a model; a model without them is one that is
  deliberately not tombstonable.
- Trigger DDL functions are versioned (touch_trigger_ddl_v1) and frozen once a migration imports them. To change trigger SQL,
  add the next version, point test_schema's trigger install at it, and write a migration swapping the triggers.
- test_schema.py diffs migrated schema against model metadata; hand-written migrations must keep that diff empty.

## Control plane API surface
Adding a resource is four steps; test_api_hygiene and test_api_parity name the exact fix when any rule below is broken.
- One model per file under models/: the table plus its api models. The generic machinery (Record, Identified, OrgOwned,
  Tombstonable, UTCDateTime) lives in models/common; mixins bring their field policy with them.
- Every table column gets a disposition, declared as ClassVar frozensets on the table: api_hidden never crosses the wire,
  api_readonly is server-owned and never accepted as input, api_immutable is create-only. Declarations union across the
  MRO, so mixins contribute theirs; hidden beats readonly beats immutable, and policy can tighten but never loosen.
- Resource representations subclass the generic markers in models/common/wire.py, parametrized by their table: RecordOut[Table] with
  every public column written flat (computed fields also listed in api_extra), RecordCreate[Table] with the writable columns,
  RecordUpdate[Table] with the mutable columns as `field: T | None = None`. The type argument is the pairing; class names are
  style, not contract. Discovery is by subclass walk; there is no registry. A table with no markers is deliberately not
  exposed; test_api_hygiene guarantees table models never cross the wire in either direction.
- Once a table has a Create or Update, its primary key must be api_readonly (server-minted) or api_immutable (caller-chosen).
- Every endpoint returns Envelope: annotate `-> Envelope[XOut]` and return `Envelope(data=XOut.model_validate(row))`.
  Rows never serialize directly. Errors stay FastAPI's `{"detail": ...}`.
- Action shapes (minted secrets, revocations) are plain BaseModel, exempt from parity by that choice. An action that
  mints a resource returns that resource's Out (compile returns BundleOut).
  Deletions return DeletedOut; revocations are not deletions and keep their own result models.
- Clients unwrap the envelope in one place each: the webapp api() wrapper, cli client payload helpers, the data plane
  poller. Never unwrap at call sites.

## Typing and lint
ty must pass clean. Do not widen to Any to silence an error, and do not add `# ty: ignore` or a blanket
`# noqa`. Fix the type or ask. Every suppression that does survive must name the exact rule and carry a
reason on the same line.
Prefer immutable construction: build with comprehensions and freeze, rather than seeding an empty
dict or list and mutating it.
Line length is 150. Do not reformat unrelated lines to fit; run `ruff format` and leave it alone.

## Testing
- The database is Postgres only. Tests share one throwaway server (testcontainers, started once per run in conftest);
  each test clones the template database keyed on tmp_path through tests/pg.py, so tests run in parallel with -n auto.
  The template is built by the alembic chain, so tests run on exactly the deployed schema; test_schema proves the
  models and create_all agree with it. Set AIRLLM_TEST_PG_URL to reuse a long-lived local server and skip the container start.
- Write the failing test first, in the same commit.
- No test that asserts a function was called. Assert behaviour or observable output.
- Adapter tests are parameterized over all registered adapters. Do not write per-adapter suites.
- Proof of fix is a real request against a running data plane, not pytest output.

## CLI
Anything started from the command line uses typer. Servers expose a typer entry point that wraps uvicorn.
Commands are resource-first (keys list, bundles compile), grouped in help panels: Setup, Resources, Testing.
Any command that outputs resource data takes -f/--format (table|json|text) via FormatOption and renders
through _print_rows with a Col spec. Do not print resource data any other way.

## Style
No comments unless asked. No emojis. No em dashes. No trailing periods in bullets.
Do not add Claude attribution to commits or PRs.
