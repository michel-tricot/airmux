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

## Self-minted instance access from key possession

`airllmcp admin create` replaced mint-root-token with a user-bound instance token, but a
standing root credential still lands in .env. The original variant (self-mint a short-lived token
from the signing key at invocation time) died with the token signing key: management keys are now
opaque and verified by database lookup, so there is no key whose possession equals root. What
survives is the Jenkins-style variant: any command with database access can mint directly through
the fat-model API, and for operators without database access, first start prints a single-use code
exchanged for a token via the API or webapp login, pairing naturally with
[service accounts](#service-accounts-as-control-plane-entities).

## Finish service accounts

Users exist with a service_account flag, memberships, and token binding, and `airllmcp init`
creates a data-plane service account to hold GW_DATAPLANE_TOKEN. What remains: nothing yet distinguishes the kinds
in behavior; when human login lands, service accounts must be excluded from it, and kind-specific
policies (token TTLs, sync-only permissions narrower than org admin) become possible. If a third
principal kind ever appears, convert the boolean to a kind enum rather than stacking flags.

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
- ApiKey.disabled and MgmtToken.revoked stay distinct from deleted_at: a disabled key drops out
  of the compiled bundle but remains visible; deleted means gone from view.
- Open policy question: what soft-deleting an org does to its keys, providers, and models
  (cascade, orphan, or forbid).

## Sign-the-bytes bundle signing

SignedBundle.payload becomes the exact serialized string the signature covers (sign once at compile
time, verify those bytes verbatim, parse BundleV1 only after the signature holds). Removes
canonical_json and the constraint that both planes run the same contract version: a lagging data
plane verifies bytes it never re-serializes, then parses with its own model, ignoring unknown
fields. Also fixes the ordering weakness of parsing attacker-controllable input before verifying.
Costs: one coordinated breaking change to SignedBundle (the last such change the envelope needs),
and bundles at rest inspect as `jq -r .payload | jq` instead of `jq .payload`. Independent of
encoding; this is the pattern signed protobufs use, without switching the contract off JSON.
Protobuf itself was considered and rejected: gzip erases the size win, Pydantic already ignores
unknown fields, and proto3 would cost HttpUrl/UUID/datetime/Literal validation. Revisit only if a
non-Python data plane or third-party contract consumers appear.

## Pluggable human login (password, OIDC, SAML via broker)

PROTOTYPE.md says do not build SSO, so this is the blueprint for when human login lands. The seam
already exists: every client authenticates with a minted management token and deps.py only ever
verifies that token, so login methods never touch authorization. Authentication's whole job is to
end in "verified user, mint a MgmtToken exactly as tokens.py does today". Revocation,
claims_are_backed, org scoping, and the data plane are untouched.

The app implements exactly two mechanisms regardless of how many providers exist:

- Local password: email plus argon2 hash, verified in-process.
- One generic OIDC relying party: authorization-code + PKCE against any issuer (authlib).

Everything else (SAML, social, magic links, directory sync) arrives through a broker that presents
as an OIDC issuer. WorkOS AuthKit is one row of OIDC configuration, not a special integration; so
are Auth0, Keycloak, Dex, authentik. SAML never touches the codebase: hand-rolled SAML SPs are a
security tarpit (XML signature wrapping) and every broker does it. Swapping WorkOS for Keycloak in
a self-hosted deployment is a config change, not a code change.

Models, one per file as usual:

- AuthIdentity: user_id, provider (`password` | `oidc:<connection-id>`), subject (the provider's
  stable sub claim, or email for password), unique on (provider, subject). Lets one user hold
  multiple login methods and resolves SSO assertions without trusting email matching forever.
- PasswordCredential: the argon2 hash, never on User. Service accounts never get one, which
  satisfies the exclusion noted in [finish service accounts](#finish-service-accounts).
- SsoConnection: OrgOwned; issuer URL, client id/secret, email_domains for home-realm discovery.
  Enterprise SSO is per-org config. An instance-wide default is a row with org_id null.

Flow: user enters email, domain matches an SsoConnection or falls back to password, OIDC callback
resolves or creates the AuthIdentity, JIT-provisions User plus OrgMembership if the connection
allows, mints a MgmtToken. If a driver seam is wanted in code it mirrors the adapter pattern: an
IdentityProvider protocol with begin(connection, redirect_uri, state) and callback(connection,
params) returning a frozen VerifiedIdentity(provider, subject, email, name); password and oidc are
the only shipped implementations, a native workos driver only if Directory Sync/SCIM is ever
wanted. Cheap to do now: keep anything from assuming User-to-credential is 1:1 so AuthIdentity
slots in without a migration headache. When login lands, the webapp should move the management
token from localStorage to an httpOnly cookie set by the callback; an XSS-readable admin token is
the first thing enterprise security review flags.

## Per-data-plane credentials with enrollment

Built 2026-08-06 from the opaque-credentials design: management keys and inference keys are now
opaque secrets (ab-mgmt-, ab-inf- prefixes), SHA-256 hashed at rest, user-bound, verified by
lookup (CP database for mgmt keys, the bundle hash index for inference keys, absence is
invalidity). The JWTs and the token signing key pair are gone; the only signature left is the
bundle's ([sign-the-bytes](#sign-the-bytes-bundle-signing)).

What remains from that design: one token per data-plane instance, bound to a DataPlane record, so
one deployment can be revoked without touching the rest and heartbeats get identity for free
(today all data planes of an org share GW_DATAPLANE_TOKEN). Bootstrap via a single-use enrollment
code rather than pasting long-lived secrets into env, pairing with the Jenkins-style variant in
[self-minted instance access](#self-minted-instance-access-from-key-possession). Console sessions
are the other unbuilt credential, detailed in
[cookie sessions for the console](#cookie-sessions-for-the-console).

## Cookie sessions for the console

The UI holds a session, not a key. Login ([pluggable human login](#pluggable-human-login-password-oidc-saml-via-broker))
ends with the server setting an opaque session token in an httpOnly Secure SameSite=Lax cookie:
a DB row like any other credential, sliding expiry of hours, absolute cap of a couple weeks. The
browser never sees a management key; a human who needs programmatic access mints a mgmt key
through the session, keeping "revoke when a laptop is stolen" (session) separate from "revoke when
CI leaks" (key).

Both doors converge in one dependency: current_actor resolves either the Authorization header
(key) or the session cookie into a frozen Actor(user_id, org_id, scopes, via, credential_id).
Header wins when both are present, never silent fallback. Routes and authorization see only Actor;
keys resolve to their owning user so membership checks and audit attribution stay uniform, with
credential_id recording which key or session acted. A few actions are session-only via the `via`
field: minting new mgmt keys and changing SSO config, so a stolen key cannot breed keys. The API
always returns plain 401 JSON; the webapp api() wrapper is where 401 becomes a login redirect.

CSRF applies only to the cookie branch. No token is minted anywhere: the api() wrapper sets a
static custom header on every request (cross-site pages cannot set custom headers without failing
CORS preflight) and the server additionally checks the browser-set Sec-Fetch-Site. Requests
authenticated by Authorization header are immune by construction and are never asked for CSRF
proof. Preconditions: no permissive CORS middleware, SameSite=Lax as the second layer.

Libraries, since the FastAPI ecosystem has no Django-grade hardened session framework: hosted
deployments can delegate the whole lifecycle to WorkOS AuthKit sealed sessions (SDK handles
refresh, JWKS, rotation; the cookie branch of current_actor just calls the SDK); self-hosted falls
back to starsessions or the session-as-a-row above, which contains no cryptography to get wrong.
fastapi-users rejected: it insists on owning the user table, which collides with the fat-model
Record design.

## Capability-based authorization on the management API

Blueprint (2026-08-06) for the missing authorization axis. Access control decomposes into three
orthogonal questions: which rows (solved by OrgOwned.owned_by, do not touch), which verbs (missing,
this idea), and via what credential (the `via` field in
[cookie sessions](#cookie-sessions-for-the-console)). Today the verbs axis is two booleans:
instance_admin and binary org membership.

The design mirrors the API-surface machinery: declarations as frozensets, a pure decision function,
and a hygiene test that makes omissions loud. One module, control_plane/authz.py:

- Permission is a StrEnum (`keys:read`, `keys:write`, `bundles:write`, `members:manage`, ...).
  Roles are nothing but named frozensets of permissions in a GRANTS mapping (viewer, editor, admin,
  and a sync role for data-plane service accounts holding only bundle read plus event write, which
  closes the kind-specific-policy gap in [finish service accounts](#finish-service-accounts)).
- OrgMembership grows a `role` column. claims_are_backed already fetches the membership row, so
  resolving role to permissions adds zero queries.
- A frozen Actor(user_id, org_id, instance_admin, permissions, via) replaces raw claims at the
  route boundary; effective permissions are role grants intersected with any scopes on the
  credential itself, which is where the scoped keys of
  [opaque credentials](#opaque-credentials-everywhere-zero-jwts) plug in without route changes.
- allowed(actor, permission) is pure, the control-plane sibling of the data plane's evaluate():
  no I/O, no session, table-testable.
- Routes declare requirements through a dependency factory:
  `@org_router.post("/keys", dependencies=[require(Permission.keys_write)])`. Routes never see
  anything but Actor and a permission name.
- A hygiene test walks app.routes and asserts every org-router route carries exactly one
  require(...) dependency, same trick as test_api_hygiene, so an unauthorized new endpoint is a
  named test failure instead of a silent hole.

Extension paths: new permission is an enum member plus GRANTS rows plus the route line; new role is
one GRANTS entry; session-only actions pass a via requirement into require(); per-resource sharing
later grows allowed() a resource parameter or swaps its body for a relationship engine (OpenFGA,
SpiceDB) while route declarations survive intact. External engines were considered and rejected for
now: a network hop on the request path for a prototype that needs three roles.

Status codes stay split by axis: wrong org is 404 via owned_by so existence never leaks, right org
but missing permission is 403 via require.

## Off-the-shelf rule engine for policy in evaluate()

Survey (2026-08-06) of fast Python rule engines, in case policy outgrows hand-rolled checks in
evaluate(). The fast ones are native cores with Python bindings; pure-Python engines all sit at
10-100us+ per eval. The fit with our architecture is the same for all of them: the control plane
stores the rule source, ships it in the bundle, the data plane compiles once at bundle load and
keeps the compiled program in memory, evaluation stays a pure sync call so evaluate() keeps its
no-I/O contract.

- zen-engine (GoRules): Rust core, single-digit microsecond evals, rules are JSON decision graphs
  (JDM) with decision tables and a visual editor. Rules-as-data fits bundle shipping exactly.
  Healthiest adoption profile: 340k downloads/month, 1.9k stars, actively developed. Caveat: use
  the pre-created sync decision object, never its async loader interface.
- CEL: non-Turing-complete boolean expressions over a context, the policy language of Kubernetes
  and Envoy, so the format outlives any binding. Rust binding (common-expression-language) is
  microsecond-fast; celpy is pure Python, slower, dependency-light. Right shape if policies are
  short expressions rather than tables.
- regopy: OPA's Rego in-process via rego-cpp, Microsoft-maintained but tiny community (47 stars).
  Worth it only if policies grow real structure.
- Also looked at: pycasbin (authz-specific, now Apache-governed), rule-engine (pleasant pure-Python
  DSL, ~10x slower), durable-rules and experta (Rete engines, unmaintained, ruled out).

The alternative that beats all of them while rules stay simple: compile bundle policy to plain
Python closures at bundle load. Nanoseconds, no dependency, trivially testable. Reach for ZEN or
CEL only when policy becomes user-authored or needs tables a human edits.

## Org id should be a minted unique id

Org ids are caller-chosen today (`--org org-dev` at init, `OrgIn.id` on /instance/orgs) and double
as the human handle. Every other record follows the server-mints-ids convention (u-, mt-, k-) with
the caller-facing name split out; orgs should too: mint `o-<hex>` at creation, keep the display
name (already derived from the admin email domain) as a mutable field, and add a slug if CLI
ergonomics need a stable human handle. Cost: org_id is threaded through bundles, tokens, the data
plane config (`data_plane.bundle.org`), and usage events, so the switch needs either slug-based
references in config or a resolve step at data-plane sync. Pairs with the surrogate-key bullet of
[soft delete](#soft-delete-on-postgres), which wants the same id/identity split for partial unique
indexes.
