# Ideas

A parking lot for ideas we have but are not building yet. Not a roadmap and not a spec. When we
defer something worth remembering, it goes here with enough context to pick up later. When we start
building one, move it out of this file and into the code or the spec.

---

## URGENT: session opening ergonomics

Open conversation (2026-08-07), resume soon. Public auth routes must each declare
`_session: SessionDep` to open the request transaction (authenticated routes inherit it through
management_claims/acting_user); forgetting one is a loud runtime failure but still a per-route
chore. The always-open-via-middleware alternative was analyzed and rejected: FastAPI exception
handlers turn HTTPExceptions into responses before middleware sees them, so middleware would
commit on 4xx paths instead of rolling back (the 401-rolls-back-the-sliding-refresh behavior
depends on the exception crossing the transaction boundary), and a middleware-held transaction
pins its connection across response send instead of ending at handler return (which is what
SessionDep's scope="function" buys). Lazy connection checkout makes the per-request cost argument
minor either way.

Proposed fix, not yet applied: attach the dependency once at the router level,
`APIRouter(prefix="/auth", dependencies=[Depends(get_session)])`, and drop the per-route _session
parameters. FastAPI's per-request dependency cache makes the redundant resolution on
authenticated routes free. Decide, apply, and consider a hygiene test that public DB-touching
routes resolve a session.

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
exchanged for a token via the API or console login, pairing naturally with
[service accounts](#service-accounts-as-control-plane-entities).

## Finish service accounts

Users exist with a service_account flag, memberships, and token binding, and a data plane carries
an org management key today rather than a service account of its own. Human login now excludes service
accounts everywhere (password login, session use). What remains:
kind-specific policies (token TTLs, sync-only permissions narrower than org admin). If a third
principal kind ever appears, convert the boolean to a kind enum rather than stacking flags.

## Non-sqlite event collection backends

The `EventOutbox` facade makes the collection method pluggable (sqlite, devnull today). Candidates:
push straight to an external telemetry sink, write to a broker for cross-host aggregation, or a
backend that survives sharing a cache dir across hosts (which the sqlite WAL backend cannot, since
WAL does not work over a network filesystem). Each is a new subclass plus one line in build_outbox.

## Soft delete on Postgres

Decision (2026-08-05, restated 2026-08-06 after the Postgres conversion): deletes stay hard and
deleted_at stays null until soft delete lands as one coordinated change. The blueprint:

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
- InferenceKey.revoked and ManagementKey.revoked stay distinct from deleted_at: a revoked key drops out
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

## Console login switch and session policy

Human login is password only (2026-08-06, argon2 on AuthIdentity) with cookie sessions (sk-sess-
opaque token, sha256 at rest, 12h sliding / 14d absolute) as a second door into the management API
through management_claims: bearer wins, cookie branch does CSRF (static X-Requested-With plus
Sec-Fetch-Site) and org scoping via X-Org-Id backed by memberships. SSO shipped alongside it and
was removed untested on 2026-08-07 to cut clutter; the design is parked in
[SSO login](#sso-login-parked).

The console rides the cookie door: password login/signup page (open self-signup via
/v1/auth/signup; fresh accounts hold nothing until granted), customFetch sends X-Requested-With
always and X-Org-Id on org-scoped calls, a sidebar org selector persisted per browser, and
a 401 anywhere flips the me query back to the login screen. The localStorage bearer is gone.

Decision (2026-08-07): self-signup is the only way a human gets a password. The admin
set/reset-password endpoint was removed as unreachable surface (no CLI or console consumer);
admins grant memberships and mint tokens after signup, and password recovery without email means
signing up fresh or an operator editing the database. Revisit when email delivery or SSO lands,
which is also what closed-signup corporate provisioning waits on.

What remains:

- Session-only actions: claims minted from a session carry the s- token_id prefix, so restricting
  mgmt-key minting to the session door is one check when wanted (a stolen
  key must not breed keys).
- Expired sessions are inert rather than deleted (the 401 rolls the request transaction back);
  a sweeper or delete-on-logout-only policy if the table ever matters.
- Hosted deployments could delegate the session lifecycle to WorkOS AuthKit sealed sessions
  behind the same cookie branch; self-hosted keeps the session row.
- Session-cookie Secure flag follows the request scheme (2026-08-08): set over https, omitted over
  http so localhost, the docker network, and `airllm quickstart` work without a dev flag. Security
  risk behind a TLS-terminating proxy that forwards as http: request.url.scheme reads http, so the
  cookie is minted without Secure and can leak over a plaintext hop. Before any such deployment,
  add ProxyHeadersMiddleware (or trust X-Forwarded-Proto) so the scheme reflects the external one,
  and consider forcing Secure on when a configured public base URL is https.

## SSO login (parked)

Built 2026-08-06, removed 2026-08-07 before any real-world use: it cluttered the auth surface
while password is the only door anyone walks through. The implementation lives in git history
(removed 2026-08-07); what existed, for when it returns:

- One generic OIDC relying party with PKCE: /auth/discover (home-realm discovery over
  email_domains, purely domain-driven so it never reveals whether a user exists), /auth/sso/start
  (mints a LoginAttempt row keyed by state, carrying nonce and code_verifier, 10 minute expiry),
  /auth/sso/callback (code exchange, id_token validated against the connection's cached jwks_uri;
  returns JSON, not a redirect, so a landing page can forward state/code via fetch).
- Per-org SsoConnection rows: issuer, client_id/secret, email_domains, jit flag, and the three
  endpoints cached from the issuer's discovery document at create time so logins never depend on
  an outbound discovery fetch. CRUD under /org/sso-connections behind sso:read/sso:write scopes.
  SAML and WorkOS stay config-only: any broker presenting as an OIDC issuer is one row.
- Identity resolution: AuthIdentity(provider="oidc:<connection_id>", subject=sub), email-match
  linking to existing users, JIT provisioning into the connection's org when jit is set, service
  accounts excluded everywhere. AuthIdentity itself survives the removal; only the oidc:* minters
  are gone.
- Signup refused emails whose domain matched a connection, so SSO domains could not shadow
  themselves with password accounts.
- Unbuilt when parked: the console side (discover call, authorize redirect, callback landing page)
  and an instance-wide default connection (org_id null) for instance admins.

Restoring means: the SsoConnection and LoginAttempt models and their tables, the three auth routes plus the org CRUD, the authlib dependency, the sso:read
and sso:write scopes, and settings.auth.public_base_url for the redirect_uri. The test plan is
[three-ring OIDC testing](#three-ring-oidc-testing).

## Three-ring OIDC testing

Testing plan (2026-08-06) for the [parked SSO implementation](#sso-login-parked), kept for its
return. Because SAML and brokers are config-only
(any issuer is one SsoConnection row), there is exactly one OIDC relying party to test, ever.
Three rings, each answering a different question; only the outermost needs Docker.

- Ring 1, below the identity seam, no network: everything downstream of a verified identity
  (AuthIdentity resolve-or-create, JIT provisioning, membership, session mint, service-account
  exclusion, invite email-match when invites land) is tested with a canned verified identity and
  ordinary route tests. The combinatorics (new user x existing identity x subject collision x
  pending invite) all live here, fast and pure.
- Ring 2, the workhorse: a ~150-line FastAPI fake IdP as a pytest fixture serving discovery,
  /authorize (302s straight back with a code, no login form), /token, and /jwks, signing real
  JWTs with a per-run key, on an ephemeral localhost port via uvicorn in a thread (authlib does
  real HTTP for discovery and token exchange, so a real socket, not ASGI mounting). The whole
  code flow drives with httpx following redirects; no browser. The point of the fake over a
  container is failure injection as a constructor argument: wrong nonce, unknown signing key,
  issuer or audience mismatch, expired or skewed tokens, missing or unverified email claim,
  tampered state, reused code, JWKS rotation mid-session. Cookie attribute assertions (httpOnly,
  Secure, SameSite=Lax) also live here where the response is a real exchange.
- Ring 3, conformance acceptance: a pinned Dex container (static YAML: staticClients plus
  enablePasswordDB, plain-HTML login form POSTable with httpx), health-checked by polling
  /.well-known/openid-configuration, as a GH Actions service or testcontainers fixture. A handful
  of scenarios only: login lands a session, second login reuses the AuthIdentity by sub, logout,
  and Dex restarted with a new signing key forces a JWKS refetch. Parameterize the happy path
  over [fake_idp, dex] like the adapter suites, so the real IdP validates the fake.

Out of CI: a nightly smoke against a hosted broker (WorkOS AuthKit test env) once one is
integrated; needs secrets and sometimes JS, never a PR gate. Password login needs none of this,
it is ring 1 plus an argon2 verify.

## Per-data-plane credentials with enrollment

Context: management and inference keys are opaque secrets (built 2026-08-06), all data planes of
an org still share GW_DATAPLANE_TOKEN, and the bundle public key is a second shared .env secret.
Enrollment gives each data plane its own credential and its pinned bundle key through a one-time
exchange, reusing the existing verify path wholesale: a per-instance credential is just a key
owned by a per-instance service account.

Revised 2026-08-08, when instance keys landed and data planes stopped recording an org: which key
type enrollment mints is now an open decision. An instance key matches how a data plane registers
(the heartbeat names no org) and is what a data plane serving several orgs would need, but it
requires the instance_admin bit on the service account, which is a lot of authority for a bundle
poller. An org-scoped management key keeps the blast radius to one org and matches today's
single-org config (data_plane.bundle.org). The quickstart trapdoor accepts either prefix, so
nothing forces the choice yet. Decide before building; the plan below is otherwise unaffected.

- EnrollmentCode table in the house shape: id, org_id, label, token_hash (sha256), expires_at
  (~24h), consumed_at. Minted by an org admin (`airllm instances enroll <org> --name rack-7` or
  console), printed once as `sk-enroll-<token_urlsafe>`. The code is the only secret carried to
  the new machine.
- `POST /v1/enroll {code}` (unauthenticated): hash lookup, reject expired or consumed, consume
  before any other work (the OIDC callback's single-use-first discipline). Then create the
  instance identity: service account named after the label, membership in the code's org, and a
  key of whichever type the decision above settles on (mint_management_key for the org-scoped
  choice, mint_instance_key for the instance-scoped one). Respond once with {token,
  bundle_public_key, org_id}. The
  exchange trusts the transport exactly once: operator-chosen URL, short-TTL single-use code;
  after it, the pinned bundle key is the anchor (which is why the key can never come from
  bundle/latest: a key fetched over the channel it verifies verifies nothing).
- Data plane config shrinks to control_plane.url + enrollment_code. First boot with no stored
  credential enrolls and persists {token, bundle_public_key, org} to a 0600 file in cache_dir;
  later boots read the file and the code is dead. Poller, heartbeat, and events are untouched;
  they just read bearer and key from the enrollment file.
- Buys: revoke one deployment (revoke its key or delete its service account; it degrades to
  serving its cached bundle, the tested control-plane-down behavior) instead of all data planes at
  once; heartbeats attributable to an enrolled identity rather than a self-reported instance_id;
  GW_DATAPLANE_TOKEN and GW_BUNDLE_PUBLIC_KEY stop being shared multi-machine secrets; unblocks
  folding init into serve since init no longer pre-writes dp credentials into a shared .env.
- Dev loop: single-host init keeps provisioning the local dp directly (it has database access);
  enrollment earns its keep from the second data plane on, the machine that does not share a disk
  with the control plane. Pairs with the Jenkins-style variant in
  [self-minted instance access](#self-minted-instance-access-from-key-possession).

## Audit redaction for secret-bearing tables

AuthIdentity and AuthSession are deliberately not @audited: the
listener snapshots whole rows into AuditLog.before/after, which would copy argon2 hashes and
session token hashes into audit rows (SsoConnection's client secrets join the list if SSO
returns). The enabler is per-table redaction: let
@audited take an exclude set (like the tombstone timestamps already excluded) or a redact-to-hash
policy, then audit identity and connection changes, which are exactly the security events an
auditor wants. The session sliding-refresh write would also need an actor story, since it happens
before current_actor is set.

## Roles over credential scopes

Credential scopes shipped (2026-08-06), inverting the original roles-first blueprint: the verbs
axis landed as restrictions on the credential (GitHub-PAT style) with roles deferred. What exists
now: Scope StrEnum and pure allowed() in authz.py, require(Scope...) declared on every org, sync,
and taxonomy route, a hygiene test in test_authz.py proving coverage (every route carries exactly
one scope, is instance-scoped, or sits in an explicit PUBLIC list), ManagementKey.scopes as a nullable
JSON column where NULL means the owning user's full authority, and `airllm tokens mint --scope`.
Init mints GW_DATAPLANE_TOKEN with the sync scope only, the first kind-specific policy from
[finish service accounts](#finish-service-accounts). A scope restricts, never expands: sessions
carry all scopes, an explicit list correctly excludes scopes invented later. 403 for
right-org-wrong-scope, 404 stays for wrong-org via owned_by.

What remains when roles arrive, layered on the same machinery with no route changes:

- Roles are named frozensets over the same Scope values in a GRANTS mapping (viewer, editor,
  admin). OrgMembership grows a `role` column; verify_management_token and the cookie door already
  fetch the membership row, so resolving role to scopes adds zero queries.
- Effective authority becomes GRANTS[role] intersected with the credential's scopes; today's
  behavior is the degenerate case where every member holds all scopes.
- Session-only actions (mint keys) add a `via` requirement to require(), so a
  stolen key cannot breed keys; claims minted from sessions already carry the s- token_id prefix.
- Instance routes carry scopes too (orgs, users, tokens read/write, taxonomy:write, added
  2026-08-06 for restricted instance credentials like a read-only auditor token); instance_admin
  stays as the row-scope gate underneath. Roles could subsume the boolean as an instance-level
  role when a second instance role is needed.
- Per-resource sharing later grows allowed() a resource parameter or swaps its body for a
  relationship engine (OpenFGA, SpiceDB) while route declarations survive intact. External engines
  stay rejected until then: a network hop on the request path for a prototype that needs three
  roles.
- Delegation must attenuate (noted 2026-08-07): once users carry claims of their own (role-derived
  scopes rather than today's implicit full authority), every path that hands authority onward must
  cap the grant at a subset of the granter's claims: an admin minting a token for a user caps at
  that user's claims, the device-flow approve caps the CLI key at the approving user's claims, and
  any future self-serve mint caps at the presenting credential's claims. Today this holds
  degenerately because every member holds all scopes and keys can only restrict; when roles land,
  the subset check must become explicit at every mint site or a viewer could mint an editor token.

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

## Scope down user listing

GET /v1/users (noted 2026-08-07) returns every user on the instance, email and org memberships
included, to any credential carrying users:read. The scope was added for restricted instance
credentials (the read-only auditor token), but it makes user listing all-or-nothing: anything that
legitimately needs to list some users (a future org-admin members page, support tooling scoped to
one tenant) must be handed cross-tenant PII to get it. Fix direction: an org-scoped members
endpoint under /org (the claims org's memberships only, backed by owned_by-style filtering), with
instance-wide listing staying an instance-credential affair; when roles land, users:read on an
org-scoped credential must mean "members of my org", never "everyone on the instance". Same
review applies to the membership mutation routes, which are instance-only today and will need org-
admin variants with the same tenant fence.

## Simplify key creation

Minting has accumulated parts (noted 2026-08-07, after mandatory labels and the CLI device flow
landed). Two shapes of duplication:

- The backing policy "may this user hold an org-scoped credential for this org" (instance_admin, or
  membership in the org) now lives in three places: mint_user_token in routes/users.py, the
  device-flow approve in routes/auth.py, and _cookie_claims in deps.py. One shared helper should
  own it; when roles land, that helper is also where delegation attenuation
  ([roles over credential scopes](#roles-over-credential-scopes)) gets enforced once instead of
  three times.
- Each credential kind carries a full set of moving parts: table, mint function in keys.py, In
  action shape, MintedOut, create route, revoke route, and now retire_for_client. Making labels
  mandatory touched every one of them. Worth collapsing toward fat-model mints (ManagementKey.mint,
  InferenceKey.mint) with keys.py keeping only the shared token format and verify paths, so the
  next field or the next credential kind is one file's change instead of five.

## Generate the CLI client from the OpenAPI spec

Half exists (noted 2026-08-07): scripts/generate-api-models.sh dumps the spec and datamodel-codegen
produces cli/api_models.py, CI fails on drift, and specs.py subclasses the generated create models
for the form-driven commands. What stays hand-written is the transport: client.py carries string
paths and commands post raw dicts (`{"label": label}`), so nothing ties a call site to the
operation it invokes; the key_id/id crash in `keys create` (fixed 2026-08-07) is exactly the drift
class this permits. The idea is to generate the operations too: one typed function per endpoint,
taking and returning the generated models, either via openapi-python-client or a small jinja pass
over the spec (ours is unusually trustworthy input: security arrays and descriptions are derived
from route markers and pinned by hygiene tests). Keep hand-written: the typer UX layer, Col
rendering, the login device flow, the profile keyring, and the envelope unwrap seam (payload/
payload_rows stay the single unwrap point per CLAUDE.md). Costs to weigh: generator pinning and
template churn, wiring the generated client to the two-door auth model (instance vs org token,
env-then-profile resolution), and generated-code noise. A cheap intermediate step with most of the
value: keep the hand transport but make every command construct its body through the generated In
models and parse responses through the generated Out models, so call sites type-check against the
spec without new tooling.

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
