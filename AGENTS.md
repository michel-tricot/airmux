# airllm gateway prototype

## Boundary rules, non-negotiable
- data_plane may never import sqlalchemy, sqlmodel, asyncpg, alembic, fastapi, or control_plane.
  The only exception is `contract/secrets/insecure_database.py`, which may use asyncpg so the
  `insecure_database` secret store can resolve a cold credential behind the data plane's
  version-keyed, single-flight TTL cache. No other contract module may import a database driver.
- The only shared import between planes is contract.
- If a feature seems to need a DB read on the request path, add a field to the bundle instead. Say so before doing it.
  Cold secret resolution through `SecretStore.get(ref)` is the sole exception; secret values and
  store-specific representations never enter the bundle contract.
- evaluate() must stay pure: no async, no network, no I/O, no datetime.now(). Under 100 lines.

## The two-sided adapter model
Canonical is the waist: N ingress dialects and M egress families all cross through it, so the cost is
N+M translators, never N times M, and policy, metering and adjustments are written once against it.
Adding an egress adapter (provider family) is one new module under egress/: subclass EgressAdapter,
set `kind`, implement the methods. Adding an ingress adapter (caller dialect) is one new module under
ingress/: subclass IngressAdapter, set `dialect`, implement claims, parse, render_response,
render_error and new_stream. Either way, edit no existing file. If you think you need to edit a
registry, the registry is wrong; fix the registry.

- A family's JSON spelling shared by both sides of the gateway lives in formats/<family>.py, pure
  functions and parse models with no url, auth, or I/O; egress and ingress adapters import it, never
  each other. Canonical to provider body is one body_of per family, every field mapped by hand. Never
  map fields reflectively; a name shared by two schemas is coincidence, not a rule. A spelling with a
  single consumer may stay inline in its adapter until a second consumer exists.
- resolve() owns dialect discrimination end to end: override header, then claims() in registry order,
  then canonical as the unclaimed default. An ingress adapter answers only "is this mine".
- The transport never parses SSE. Framing lives once in egress/base.frame_sse, the single source
  of truth for the SSE machine; an adapter's frame() adds only its dialect, like OpenAI's [DONE].
- StreamState is adapter-shaped. Construct it in new_stream_state(), never in the transport.
- finalize(state) must return a valid CanonicalResponse at ANY point in the stream, including
  after a client disconnect. Cancellation accounting depends on this.
- frame() and transform_stream_event() stay synchronous so the streaming path is testable as a
  pure fold over a recorded byte log.

## Control plane data access
- All DB access goes through the fat-model API on control_plane.models: Record.get/find/first/save/delete, OrgOwned.owned_by, Identified.find_by_id.
  The shared `InsecureDatabaseSecretStore` is the sole exception: both planes use its three fixed,
  parameterized asyncpg statements against `insecure_vault_secret`, outside the ambient management
  transaction. No other control-plane path may use it for database access.
- The session is ambient (ContextVar in control_plane.db). One transaction per request, committed at request end; save() flushes, never commits.
- Routes take no SessionDep unless they need raw SQL. Raw sessions are only for what the model API cannot express:
  aggregates, dialect-specific atomic upserts. Do not grow Record into a query builder to absorb them.
- Schemas are fat: raw operations a resource needs are wrapped as named methods on its model running through the
  ambient session, so routes stay free of SessionDep and the domain operation has one home. Same for compound
  lookups (Org.joined_by, Org.personal_of, CliAuthRequest.by_user_code): promote them to the model instead of
  composing find() calls in routes. Prefer constraints over guard code: a uniqueness rule enforced by the schema
  (org.personal_for) beats a conditional update defending the same invariant.
- Org-scoped lookups go through owned_by, never a hand-rolled org_id check. NotOwnedError maps to 404 in app.py.
- Non-request code (lifespan, CLI, background tasks) opens its own transaction(); never let a spawned task inherit a request session.
- @audited marks tables for audit coverage; the registry is the source the audit trigger DDL is generated from.
  Database triggers (audit_trigger_ddl_v1, versioned and installed by the migrations like the touch
  triggers) write before/after AuditLog rows for every write path including Core statements, excluding the
  database-owned timestamps. The acting user reaches the triggers through the transaction-local app.user_id GUC.
  Stamping lives in deps (`authority` for bearer or session routes and `cookie_user` for browser-only routes).
  The route-level stamps are signup and CLI key delivery, where the principal becomes known only mid-handler;
  setup and CLI work stamp explicitly.
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
- Clients unwrap the envelope in one place each: the console's customFetch, cli client payload helpers, the data plane
  poller. Never unwrap at call sites.

## Console UI composition
- Before writing styled markup under `apps/console`, inspect `components/ui/elements.tsx`,
  `components/shared`, and the vendored `components/ui` primitives
- Pages compose shared components; they never rebuild an existing button, field, dialog, select,
  radio group, table, tabs, empty state, or other interactive pattern with native elements and utilities
- `components/ui` owns low-level accessible behavior, `elements.tsx` owns the themed application API,
  and `components/shared` owns reusable product-level compositions
- Extend an existing component with a focused prop or variant before creating a parallel implementation
- Extract a stable UI concept when it gains a second real caller, or immediately when accessibility-sensitive
  behavior needs one implementation; keep genuinely page-specific layout local
- Direct `@radix-ui` imports belong in vendored primitive modules only; application wrappers compose those local primitives
- Never delete a UI primitive from import counts alone; first check whether an application wrapper is
  manually recreating the same behavior and migrate it to composition

## Interface boundaries, non-negotiable
- Domain and internal types describe only valid states. Do not make a required value optional, use a
  free-form string for a closed vocabulary, or return an untyped dict because validation happens later
- Uncertain and legacy input is accepted only at a wire, file, or environment parser and normalized once
  into the strict internal type. Backward compatibility belongs in a BeforeValidator or adapter, never in
  every consumer
- Conditional shapes are discriminated unions with one model per valid state. Do not represent state
  machines as one model whose fields become conditionally required through `T | None`
- Closed vocabularies use a shared Literal or StrEnum. Identifiers use their domain type, including UUID,
  after boundary normalization
- A database column is non-null when the domain requires the value. Tightening a persisted field includes
  a backfill migration and a migration test that covers legacy data
- CLI control-plane responses are decoded into generated `api_models` in `cli.client`. Commands never
  consume raw response dicts, and payload helpers always require the expected response model
- Optional update fields, partial stream deltas, provider wire JSON, JSON Schema values, and the canonical
  request's documented top-level passthrough are intentionally open. Do not generalize those exceptions
- Every tightened boundary gets a behavior or generated-schema test proving invalid states are rejected
  and valid legacy input is normalized

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

## Delivery
- After completing any task that changes project files, commit the finished work, push its branch,
  and open a draft pull request unless the user explicitly requests local-only changes.
- Use an isolated worktree and a dedicated branch so unrelated changes never enter the pull request.
- The pull request description names the user impact and the checks that prove the change.

## Style
No comments unless asked. No emojis. No em dashes. No trailing periods in bullets.
Name variables after the entity they hold, never the storage shape: auth_request, key, membership,
not row, obj, record. Docstrings and errors speak the domain language too.
Do not add Claude attribution to commits or PRs.
