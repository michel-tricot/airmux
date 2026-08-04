# Gateway prototype: implementation spec (Python)

Target: a working vertical slice that proves the control plane / data plane boundary. Not a product. Written to be handed to Claude Code as the source of truth.

**The one thing this prototype exists to prove:** the data plane serves at full function, including a cold start, with the control plane switched off for 24 hours. Everything here exists to make that testable in week four instead of after the first sovereign deal.

---

## 0. Stack decision

Python 3.13, uv workspace, ruff, ty. Line length 150. Full toolchain config in §10.

**Control plane:** FastAPI, SQLModel over SQLAlchemy 2.0 async, Alembic, asyncpg, Postgres.
**Data plane:** Starlette directly, no FastAPI, uvicorn with uvloop, httpx, Pydantic v2, cryptography, tiktoken.

Starlette rather than FastAPI on the data plane is deliberate and worth keeping. The data plane has one real endpoint plus health, so FastAPI's per-request Pydantic validation and dependency machinery buy nothing and put a framework in the hot path. This is the "choose twice" argument made concrete in one line of dependencies.

Python also makes the ADP swap in §9 real rather than theoretical, since the connector work is already Python.

**On the performance question.** A Python data plane will not match a native one, and that is fine. This prototype validates an interface. Keep the data plane under roughly three thousand lines and the PyO3 exit stays open later: ship a Rust core inside the same wheel, opt in per model, fall back to Python on error, no v2 and no migration event. That option only exists if the data plane stays small. Treat its line count as a design constraint.

---

## 1. Repo layout

```
gateway/
  pyproject.toml            # uv workspace root
  packages/
    contract/               # pyproject.toml, src/gw_contract/
  apps/
    control-plane/          # pyproject.toml, src/control_plane/
    data-plane/             # pyproject.toml, src/data_plane/
    cli/                    # seed, compile, verify, loadgen
  .importlinter
  docker-compose.yml        # postgres only
  CLAUDE.md
```

**Hard rule, enforced in CI.** `apps/data-plane/pyproject.toml` may not declare `sqlalchemy`, `sqlmodel`, `asyncpg`, `psycopg`, `alembic`, or `fastapi`. No module under `data_plane` may import `control_plane`. Enforced two ways:

1. An `import-linter` forbidden contract (`.importlinter`) run in CI.
2. A test that imports `data_plane` in a subprocess and asserts `sqlalchemy` and `fastapi` are absent from `sys.modules`.

If a feature seems to need a database read on the request path, the bundle is missing a field. Add the field.

Do not create a shared utils package. The only common import is `gw_contract`.

---

## 2. `gw_contract`

Everything crossing the boundary, in Pydantic v2, versioned. Both planes import this and nothing else in common.

### 2.1 Bundle

```python
class KeyEntry(BaseModel):
    key_id: str
    key_hash: str  # sha256(plaintext), hex
    org_id: str
    allowed_models: list[str]  # ["*"] permitted
    disabled: bool = False


class ProviderEntry(BaseModel):
    provider_id: str
    kind: Literal["openai_compatible", "anthropic"]
    base_url: HttpUrl
    credential_ref: str  # NOT a secret, see 2.3


class ModelEntry(BaseModel):
    model_id: str  # what the caller asks for
    provider_id: str
    upstream_model: str  # what the provider is sent
    input_price_per_mtok: float
    output_price_per_mtok: float
    context_window: int
    capabilities: list[str]  # "streaming","tools","vision"


class BundleV1(BaseModel):
    schema_version: Literal[1] = 1
    bundle_id: UUID
    org_id: str
    issued_at: datetime
    expires_at: datetime  # staleness bound, see §6
    keys: list[KeyEntry]
    revocations: list[str]
    catalog: Catalog  # providers + models


class SignedBundle(BaseModel):
    payload: str  # canonical JSON of BundleV1
    signature: str  # ed25519, base64
    signing_key_id: str
```

Signing with `cryptography` Ed25519. Canonical JSON means sorted keys, no whitespace, UTF-8. The public key ships in data plane config. A bundle that fails verification is rejected and the previous one keeps serving.

### 2.2 Events

```python
class UsageEventV1(BaseModel):
    schema_version: Literal[1] = 1
    event_id: UUID  # idempotency key
    request_id: str
    occurred_at: datetime
    org_id: str
    key_id: str
    model_id: str
    provider_id: str
    bundle_id: UUID  # which policy version served this
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    status: Literal["ok", "upstream_error", "denied", "timeout", "cancelled"]
    stream: bool
```

At-least-once, idempotent on `event_id`. The control plane upserts.

### 2.3 Secret path

`credential_ref` is a URI resolved locally by the data plane: `env:ANTHROPIC_API_KEY`, `file:/run/secrets/anthropic`, `vault:secret/data/x#key`. Implement `env:` and `file:` only.

The control plane never stores or sees a provider secret. Build it this way from the first commit. Managed mode is a later special case of sovereign mode; the reverse is not reachable, because building managed first bakes in the assumption that you hold the credential.

---

## 3. Control plane

SQLModel tables: `Org`, `ApiKey`, `Provider`, `Model`, `Bundle`, `UsageEvent`, `DataPlaneInstance`. Alembic for migrations from the start, not `create_all`.

`ApiKey` stores `key_hash` (sha256 hex) and `key_prefix` for display. Never plaintext. Plaintext is returned once, at creation.

| Method | Path | Notes |
|---|---|---|
| POST | `/admin/orgs` | |
| POST | `/admin/keys` | returns plaintext once |
| DELETE | `/admin/keys/{id}` | disables, adds to revocations |
| POST | `/admin/providers` | takes `credential_ref`, rejects anything shaped like a secret |
| POST | `/admin/models` | |
| POST | `/admin/bundles/compile` | compile, validate, sign, persist, return bundle_id |
| GET | `/v1/bundle/latest` | data-plane auth, returns SignedBundle |
| POST | `/v1/events` | batch, idempotent upsert on event_id |
| POST | `/v1/heartbeat` | instance_id, version, bundle_id, last_seen |

**The compiler is the module that matters.** `compile(session, org_id) -> BundleV1` reads every table, builds the model, validates, canonicalizes, signs, persists with a monotonic version. It must be a pure function of database state so it can be diffed and replayed. Set `expires_at = issued_at + STALENESS_BOUND`.

Admin auth for the prototype is one static bearer from env. Do not build SSO.

---

## 4. Data plane

### 4.1 Boot sequence

1. Load config from env: control plane URL, DP token, bundle public key, cache dir, staleness policy.
2. Read cached bundle from disk, verify signature. If valid and unexpired, serve immediately.
3. Start serving. Do **not** block startup on reaching the control plane.
4. Start the bundle poller (30s) and event flusher (5s) as `asyncio` tasks in the Starlette lifespan.
5. Replay buffered events from disk.

No cached bundle and control plane unreachable: readiness fails, liveness stays green, log loudly.

### 4.2 Request path

```
ingress -> auth -> policy -> route -> adapter.transform_request
        -> transport -> adapter.transform_response | streaming
        -> meter -> emit event
```

**Auth.** sha256 the bearer, look it up in a `dict[str, KeyEntry]` built once per bundle swap. Check the revocation set. Zero I/O.

**Policy.** A pure synchronous function, and it must stay that way:

```python
def evaluate(req: CanonicalRequest, key: KeyEntry, bundle: BundleV1, now: datetime) -> Decision
```

`Decision` is `Allow(model, provider)` or `Deny(reason, status)`. No `async`, no network, no `datetime.now()` inside. This is the function that rots first in every gateway of this shape: one network call gets added for a lookup, then a cache, then a fallback, and it ends up a thousand-line builder nobody can reason about. Keep it under 100 lines and unit-test it against a fixture bundle with no server running.

**Adapter interface.** Eight abstract methods. The obvious design is six, but that version assumes SSE framing is universal and has no way to produce a response from a partial stream. Both assumptions break on the second adapter.

```python
class ProviderAdapter(ABC):
    kind: ClassVar[str]

    @abstractmethod
    def validate_environment(self, p: ProviderEntry) -> None: ...
    @abstractmethod
    def transform_request(self, req: CanonicalRequest, m: ModelEntry) -> UpstreamRequest: ...
    @abstractmethod
    def transform_response(self, raw: bytes, ctx: Ctx) -> CanonicalResponse: ...

    @abstractmethod
    def new_stream_state(self, ctx: Ctx) -> StreamState: ...
    @abstractmethod
    def frame(self, chunk: bytes, state: StreamState) -> Iterator[RawEvent]: ...
    @abstractmethod
    def transform_stream_event(self, ev: RawEvent, state: StreamState) -> list[CanonicalChunk]: ...
    @abstractmethod
    def finalize(self, state: StreamState) -> CanonicalResponse: ...

    @abstractmethod
    def map_error(self, e: Exception) -> CanonicalError: ...
```

Three rules govern this interface.

**Framing belongs to the adapter, not the transport.** `frame()` takes raw bytes off the socket and yields provider-shaped events. OpenAI is `data: {...}` with a `[DONE]` sentinel, Anthropic uses named SSE events, Gemini streams a JSON array over chunked transfer, and Bedrock uses AWS binary event-stream framing that is not SSE at all. If the transport parses SSE, Bedrock cannot be added without special-casing the transport, which is the registration sprawl this spec exists to avoid. `frame()` also owns the buffer for a partial line split across TCP reads, which is why it takes `state`.

**`StreamState` is adapter-owned and adapter-shaped**, which is why `new_stream_state()` exists. It accumulates whatever that provider needs: OpenAI streams tool-call arguments as string fragments that must be concatenated across chunks, Anthropic tracks content block indices, both carry reasoning blocks, and every adapter needs the framing buffer.

**`finalize(state)` must return a valid `CanonicalResponse` at any point in the stream.** This is the load-bearing invariant. Call it after the last event for a normal completion, and call it from the cancellation handler for partial accounting. It absorbs what would otherwise be a separate `extract_usage`, since usage belongs on the response anyway. Put this rule in the docstring; it is what makes the cancel-and-still-meter test pass.

Mid-stream errors fall out of this cleanly. Providers send those as an event after a 200, so `transform_stream_event` raises and `map_error` handles it, rather than forcing an error through the HTTP status path where it does not fit.

Keep `frame` and `transform_stream_event` synchronous. Async there buys nothing and costs you the ability to test the entire streaming path as a pure fold over a recorded byte log, with no event loop and no server.

Note that `transform_request` sees `req.stream` and needs it: OpenAI only returns usage in a stream if the request carries `stream_options: {"include_usage": true}`, and injecting that is the adapter's job.

**Registration is derived, never duplicated.** `adapters/__init__.py` walks the package with `pkgutil.iter_modules`, imports each submodule, and collects every `ProviderAdapter` subclass by its `kind`. Adding an adapter means adding one module and touching nothing else.

This is the most important structural rule in the spec. The common failure mode is registration sprawl, where adding one provider means edits across eight or nine files outside its own directory, none of them reachable from the code being written. That is what makes agent-generated adapters unreliable, because an agent cannot reach touchpoints the artifact it is producing does not point at. If registration cannot be derived, the design is wrong.

**Build two adapters, structurally different.** `openai_compatible` (around 80 lines) and `anthropic` (around 350, native Messages shape). Two compatible providers teach you nothing, because the second is a subclass. The native one is where you find out whether the interface is real.

**Streaming.** `httpx.AsyncClient.stream` inside a Starlette `StreamingResponse`. The transport hands raw bytes to `adapter.frame()` and never parses SSE itself. Each yielded event goes through `transform_stream_event`, and the resulting canonical chunks are serialized as SSE to the client.

Client disconnect arrives as `anyio.get_cancelled_exc_class()` in the generator. Catch it, let the `httpx` stream context manager close the upstream socket, call `adapter.finalize(state)` for partial counts, emit the usage event with `status="cancelled"`, then re-raise. Emitting on cancel is the part people forget, and `finalize` being valid mid-stream is what makes it possible.

**Transport.** One module-level `httpx.AsyncClient` with `Limits(max_connections=..., max_keepalive_connections=...)`, explicit connect and read timeouts, HTTP/2 on, one retry with jitter on connect errors only. Never retry a request that has begun streaming.

**Metering.** Token counts from the provider response where given, `tiktoken` estimate where not. Cost from bundle pricing, never from a lookup service.

**Local state.** Bundle cache at `${CACHE_DIR}/bundle.json`, written to a temp file then `os.replace` for atomicity. Event buffer as append-only JSONL at `${CACHE_DIR}/events.jsonl`, truncated after a successful flush. Both survive restart.

### 4.3 Bundle swap

Poll, verify, compare `bundle_id`, swap by rebinding a single attribute on a holder object. Attribute rebinding is atomic under the GIL, and in-flight requests keep the bundle they captured at entry. Write to disk after the swap. Never mutate a bundle in place; `BundleV1` should be frozen (`model_config = ConfigDict(frozen=True)`).

---

## 5. Milestones

Each stage runs and demos on its own.

**M1. Contract and one adapter.** `gw_contract` with schemas and signing. Data plane serving `POST /v1/chat/completions` non-streaming against `openai_compatible`, reading a hardcoded bundle file from disk, no control plane at all. Proves the request path.

**M2. Streaming.** SSE end to end, cancellation propagation, usage extraction. Do not defer this. It is where chunk assembly, token accounting and cancellation interact, and retrofitting it is the most expensive item on the list.

**M3. Control plane and compiler.** SQLModel schema, Alembic, admin CRUD, `compile()`, signing, `GET /v1/bundle/latest`. Data plane polls instead of reading a file. Revocation lands within one poll interval.

**M4. Second adapter.** Anthropic native. Both pass the same conformance suite. The eight-method interface above was already corrected for the three things a native adapter breaks (framing, state ownership, partial finalize), so if it still has to change here, that finding is worth more than the code. Write down what changed and why.

**M5. Event path and acceptance.** Metering, local buffering, replay, idempotent ingest. Then run §6.

---

## 6. Acceptance tests

These are the spec. Code that does not pass them is not done.

1. **Boundary.** `lint-imports` fails CI on any forbidden import, and a subprocess test asserts `sqlalchemy` and `fastapi` are not in `sys.modules` after importing `data_plane`.
2. **Control plane down.** Stop the control plane. Data plane serves 100 requests. Then kill and cold-restart the data plane. It still serves, from the on-disk bundle. This is the test the architecture exists to pass.
3. **Event replay.** With the control plane down, generate 50 requests. Restart it. All 50 events land exactly once, verified by distinct `event_id` count.
4. **Revocation.** Revoke a key, recompile, data plane rejects within one poll interval.
5. **Adapter conformance.** One `pytest.mark.parametrize` suite over both adapters: non-streaming, streaming, tool call, upstream 429, upstream timeout, malformed response, mid-stream error event after a 200. Same assertions for both. Fake upstream via `respx`.
5a. **Stream and non-stream agree.** For the same prompt, folding the recorded stream through `frame`, `transform_stream_event` and `finalize` must produce the same `CanonicalResponse` as `transform_response` on the non-streaming reply. Streaming assemblers and response transforms drift apart as soon as they are maintained separately; this assertion is the only thing that stops it.
5b. **Streaming path is a pure fold.** The M2 streaming tests run against a recorded byte log with no event loop, no server and no network, splitting the log at adversarial boundaries (mid-line, mid-multibyte-character) to prove `frame()` buffers correctly.
6. **Cancellation.** Abort a stream client-side. Assert the upstream connection closed and a usage event was emitted with partial counts and `status="cancelled"`.
7. **Staleness.** Set `expires_at` in the past. Data plane behaves per configured policy (serve-and-warn or refuse) and logs it. Pick the default deliberately.
8. **Policy purity.** `evaluate()` tests run with no server, no network, no Postgres, no event loop.

---

## 7. Out of scope

Console, SSO, SCIM, RBAC beyond key-to-model, routing strategies, failover beyond one retry, guardrails, cache, tool loop, retrieval, plugin runtime, batches, embeddings, images, audio, realtime, passthrough, Responses API, Gemini.

**Budgets: meter but do not enforce.** Enforcement is eventually consistent under partition, and the fail-open versus fail-closed choice is much easier with a month of real numbers than in advance.

---

## 8. CLAUDE.md to drop in the repo

```md
# Gateway prototype

## Boundary rules, non-negotiable
- data_plane may never import sqlalchemy, sqlmodel, asyncpg, alembic, fastapi, or control_plane.
- The only shared import between planes is gw_contract.
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

## Typing and lint
ty must pass clean. Do not widen to Any to silence an error, and do not add `# ty: ignore` or a blanket
`# noqa`. Fix the type or ask. Every suppression that does survive must name the exact rule and carry a
reason on the same line.
Prefer immutable construction: build with comprehensions and freeze, rather than seeding an empty
dict or list and mutating it.
Line length is 150. Do not reformat unrelated lines to fit; run `ruff format` and leave it alone.

## Testing
- Write the failing test first, in the same commit.
- No test that asserts a function was called. Assert behaviour or observable output.
- Adapter tests are parameterized over all registered adapters. Do not write per-adapter suites.
- Proof of fix is a real request against a running data plane, not pytest output.

## Style
No comments unless asked. No emojis. No em dashes. No trailing periods in bullets.
Do not add Claude attribution to commits or PRs.
```

---

## 9. Swap point

If this is meant to land on ADP rather than model routing, the only change is `ProviderAdapter` becoming `SystemAdapter` and the second implementation being Salesforce or Workday instead of Anthropic. Pick a genuinely hard system, not a REST-clean one, for the same reason the native LLM adapter beats a second compatible one.

Python makes that swap cheap, since the connector side is already Python. Everything else is unchanged: same boundary, same bundle, same acceptance test, same amount of work.

---

## 10. Toolchain and code quality

uv for packaging, ruff for lint and format, ty for type checking. Line length 150.

### 10.1 Root `pyproject.toml`

```toml
[project]
name = "gateway"
version = "0.1.0"
requires-python = ">=3.13"

[tool.uv.workspace]
members = ["packages/*", "apps/*"]

[tool.uv.sources]
gw-contract = { workspace = true }

[dependency-groups]
dev = [
  "ruff>=0.14",
  "ty>=0.0.50",
  "pytest", "pytest-asyncio", "respx", "anyio",
  "import-linter",
  "pre-commit",
]

[tool.ruff]
line-length = 150
target-version = "py313"
src = ["packages/contract/src", "apps/control-plane/src", "apps/data-plane/src", "apps/cli/src"]

[tool.ruff.format]
docstring-code-format = true

[tool.ruff.lint]
select = [
  "F", "E", "W",          # pyflakes, pycodestyle
  "I",                    # isort
  "N",                    # pep8-naming
  "UP",                   # pyupgrade
  "ANN",                  # annotations required
  "ASYNC",                # blocking calls in async, see 10.3
  "S",                    # bandit
  "BLE",                  # blind except
  "B",                    # bugbear
  "A",                    # builtin shadowing
  "C4",                   # comprehensions
  "DTZ",                  # naive datetimes, see 10.3
  "T10",                  # leftover breakpoints
  "EM",                   # exception message literals
  "FA",                   # future annotations
  "ISC",                  # implicit str concat
  "ICN",                  # import conventions
  "LOG", "G",             # logging correctness and format
  "INP",                  # implicit namespace packages
  "PIE",
  "T20",                  # no print
  "PYI",
  "PT",                   # pytest style
  "Q",                    # quotes
  "RSE", "RET",
  "SLF",                  # private member access
  "SIM",
  "TID",                  # tidy imports, incl. banned-api
  "TC",                   # type-checking blocks
  "ARG",                  # unused arguments
  "PTH",                  # pathlib over os.path
  "ERA",                  # commented-out code
  "PGH",                  # blanket noqa / blanket type ignore
  "PL",                   # pylint C/E/R/W
  "TRY",                  # tryceratops
  "FLY", "PERF", "FURB",
  "RUF",
]
ignore = [
  "COM812",  # conflicts with the formatter
  "ISC001",  # conflicts with the formatter
]

[tool.ruff.lint.per-file-ignores]
"**/tests/**"                  = ["S101", "PLR2004", "ANN", "ARG", "SLF001", "INP001"]
"**/migrations/versions/*.py"  = ["ALL"]
"apps/cli/**"                  = ["T201"]

[tool.ruff.lint.isort]
known-first-party = ["gw_contract", "control_plane", "data_plane"]
required-imports = ["from __future__ import annotations"]

[tool.ruff.lint.flake8-annotations]
mypy-init-return = true

[tool.ruff.lint.flake8-type-checking]
runtime-evaluated-base-classes = ["pydantic.BaseModel", "sqlmodel.SQLModel"]

[tool.ty.environment]
python-version = "3.13"

[tool.ty.terminal]
error-on-warning = true
```

`runtime-evaluated-base-classes` is not optional. Without it the `TC` rules will move Pydantic and SQLModel field types into `if TYPE_CHECKING` blocks, and both libraries resolve annotations at runtime, so models break at import with errors that look nothing like a lint problem.

`D` (pydocstyle) is deliberately not selected. The repo rule is no comments unless asked, and enforcing docstrings everywhere fights it. The one place a docstring is required is the `finalize()` invariant in §4.2, which is a review item, not a lint rule.

### 10.2 Boundary enforced by the linter

`apps/data-plane/pyproject.toml` inherits the root config and adds a banned-import list. Ruff resolves the nearest config, so this applies only inside the data plane:

```toml
[tool.ruff]
extend = "../../pyproject.toml"

[tool.ruff.lint.flake8-tidy-imports.banned-api]
"sqlalchemy".msg    = "data plane must never touch a database, add a field to the bundle"
"sqlmodel".msg      = "data plane must never touch a database, add a field to the bundle"
"asyncpg".msg       = "data plane must never touch a database, add a field to the bundle"
"psycopg".msg       = "data plane must never touch a database, add a field to the bundle"
"alembic".msg       = "control plane only"
"fastapi".msg       = "data plane runs on bare Starlette, see spec 0"
"control_plane".msg = "planes communicate only through gw_contract"
```

This is now the third layer on the same rule, alongside the `import-linter` contract and the `sys.modules` subprocess test in §6.1. Three layers is not paranoia. It is the one invariant the whole design rests on, and it is the one an agent will breach first, because reaching for a database is the locally obvious fix.

### 10.3 Two rule families that will earn their keep here

**`ASYNC`.** The data plane does file I/O on the bundle cache and the event buffer from inside an async server. `ASYNC230` catches a plain `open()` in an async function, which is exactly the bug that stalls the event loop under load and is invisible until concurrency.

**`DTZ`.** Bundle staleness is a datetime comparison against `expires_at`. A naive datetime anywhere in that path is a correctness bug in the sovereign story, not a style issue. `DTZ005` bans bare `datetime.now()`, which also happens to enforce the injected-clock rule that keeps `evaluate()` pure.

`EM` plus `TRY003` together force real exception classes instead of long string literals at raise sites. That is more ceremony than a prototype normally wants, and it is worth keeping, because `map_error` in the adapter interface needs a typed exception taxonomy to map from.

### 10.4 On ty specifically

ty is at 0.0.x and still beta as of August 2026, with 1.0 targeted for this year. Two consequences worth planning around rather than discovering.

First, Astral's own pre-stable list still includes first-class support for large third-party libraries, and SQLModel over SQLAlchemy is exactly that weak spot. So gate CI on ty for `packages/contract` and `apps/data-plane`, which are pure Pydantic, stdlib and httpx, and run it non-gating on `apps/control-plane` until it comes back clean. That keeps the strong bar on the code you will eventually port to Rust, without stalling the build on ORM stub gaps.

Second, ty checks unannotated function bodies by default, which mypy skips. On a greenfield codebase where `ANN` already requires annotations everywhere, that is a feature rather than a migration cost.

Do not pin ty loosely. Pin an exact version and bump it deliberately, because a 0.0.x bump can change the diagnostic set under you mid-milestone.

### 10.5 CI

```
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run ty check packages/contract apps/data-plane
uv run ty check apps/control-plane || true
uv run lint-imports
uv run pytest
```

Same commands in `.pre-commit-config.yaml`, minus the test run. No `--fix` in CI; formatting is either committed or the build fails.