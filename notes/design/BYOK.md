# BYOK: workspace-supplied provider credentials

A workspace brings its own provider API keys, plural per provider. The values live in a secret store
the control plane writes and the data plane reads, named once in config and reached through one
facade. They are never persisted anywhere else: not in the bundle, not in `bundle.payload`, not in
the data plane's disk cache, not in `audit_log`, not in `.env` or `airllm.yml`, not in a log line.

## Core shape

One credential table, three scopes, resolved workspace then org then platform.
`Provider.credential_ref` is deleted and an operator key becomes a `scope=platform` row, so BYOK is
not a second mechanism bolted beside the first. One bundle field, one resolver, no special case on
the request path.

```
console/CLI --plaintext--> control plane --put--> SECRET STORE <--get-- data plane --> provider
                                |                      ^
                                | rows: no value, no location
                                | bundle: refs, priorities, versions
                                +----------------------+
```

Tier selection is fixed in v1 (policy is [deferred](#deferred-to-the-next-version)):

- **Empty tier cascades**: the most specific tier holding any enabled credential wins
- **Exhausted tier does not cascade**: once a tier is chosen, a 401 or 429 there never moves the
  request to a broader tier

The second rule is the one that matters: a broken workspace key must never silently move an org's
spend onto the platform account. The first keeps platform credentials and `airllm quickstart`
working, which deny-on-empty would break.

Known v1 limitation: an org cannot require BYOK, so a workspace with no credential falls to the
platform key. That lever is a policy field in the next version.

## The store facade

Config names one store and every access after that is the same three calls, so nothing outside
`contract/secrets/` knows whether a value sits in a file, an environment variable, or a vault.

```python
class SecretStore(ABC):
    kind: ClassVar[str]
    writable: ClassVar[bool] = False

    async def get(self, ref: SecretRef) -> Secret: ...
    async def put(self, ref: SecretRef, secret: Secret) -> None: ...
    async def delete(self, ref: SecretRef) -> None: ...
```

The decisive rule is that **callers name a secret, never a location**:

```python
class SecretPurpose(StrEnum):
    provider = "provider"


@dataclass(frozen=True)
class SecretRef:
    purpose: SecretPurpose  # the family
    service: str  # what it authenticates to: a provider name today
    name: str  # the handle that lets one service hold several: prod, backup
    secret_id: UUID  # what actually makes it unique
    org_id: UUID | None = None  # absent for a platform secret
    workspace_id: UUID | None = None  # absent for platform and org secrets
```

Provider credentials are the first purpose and the reason the package exists, but nothing in it is
provider-shaped. A signing key, an outbound integration credential, or anything else the platform
holds on someone's behalf is a new `SecretPurpose` member and no new mechanism.

Consequences worth stating, because they delete design surface rather than add it:

- **There is no location string anywhere.** Not a column, not a bundle field, not a config value.
  Nobody can author, forge, or leak one, so the whole class of `file:/proc/self/environ` injection
  vanishes by construction rather than by validation
- A store maps a ref to its own address in its own module. Hierarchical stores use `path_segments`,
  purpose first and fixed depth, so families stay separable and an org secret and a workspace secret
  can never resolve to the same place. A flat store flattens however it likes and nothing else knows
- Read-only stores implement `get` and inherit the refusals, so a backend declares what it can do by
  what it overrides. The control plane checks `writable` at startup, so an env-backed instance
  refuses BYOK as a misconfiguration instead of failing a credential creation at runtime

Each backend also brings its own config, so there is no shared settings object accumulating every
backend's fields and no factory with a branch per kind:

```python
class SecretStoreConfig(BaseModel, ABC):  # frozen, extra="forbid"
    kind: str

    def build(self) -> SecretStore: ...


SecretsConfig = Annotated[MemoryStoreConfig | FileStoreConfig | EnvStoreConfig, Field(discriminator="kind")]
```

- `kind` selects which backend parses the settings, so `root` is the file store's business and
  nobody else's
- Extra keys are refused. A setting meant for another backend, or a misspelled one, means the store
  is not configured the way whoever wrote it believes, and a store quietly running on defaults is
  how credentials end up somewhere nobody intended
- A config builds its own store, so adding a backend is one new module plus one member in the union.
  There is nothing else to edit

Both planes read their own copy of this section and must name the same store, because one writes what
the other reads.

Shipped: `memory` (tests and single-process dev), `file` (one 0600 file per secret under a root,
which is a real single-host deployment), `env` (read only, quickstart and single-tenant instances
whose provider keys already arrive as environment variables).

The env store resolves a provider credential to **`{SERVICE}_API_KEY`**, the name every provider SDK
documents and the one `taxonomy/taxonomy.yml` used before credentials became a resource, so an operator
running on the environment configures nothing new. `{prefix}_{PURPOSE}_{SERVICE}` takes precedence,
for an environment that already means something else by `OPENAI_API_KEY` and as the only name a
non-provider purpose answers to.

**Scope and name are deliberately not part of the lookup**, so every credential for a provider
resolves to the same variable whatever its row says. That is not a compromise, it is what the
environment is: it holds one value per provider and cannot hold more. Trying to key it per
credential would only produce variable names nobody can set.

The consequence is worth stating plainly rather than discovering: an instance on this store bills
every workspace to one upstream account per provider, so **BYOK on it is nominal**. It serves
single-tenant deployments and development. Per-tenant keys need a store that can hold more than one
value per provider, which is what `file` and the vault backends are for.

Next, once the design has been exercised through the planes: **HashiCorp Vault KV v2**, chosen over
the cloud secret managers because hierarchical paths map onto `path_segments` directly while
AWS/GCP/Azure force a flattened id, because a prefix-scoped read policy pins the data plane token to
one subtree, because integer KV v2 versions match the `version` column one to one, because `destroy`
plus `max_versions` gives real rotation hygiene, and because per-secret pricing bites precisely when
credentials are plural per workspace per provider. It is one module behind the facade.

## Shared code

`contract/credentials.py` is already the cross-plane credential agreement, so `contract/secrets/`
extends that precedent instead of adding a fourth shared lib. Both planes build a store from their
own config: the control plane needs a writable one, the data plane only ever calls `get`.

## Data model

```
ProviderCredential(Record, Identified, OrgOwned, Tombstonable)
  org_id
  workspace_id: UUID | None    # set iff scope == workspace, composite FK to (workspace.id, workspace.org_id)
  provider_id -> provider.id
  scope: platform | org | workspace
  name: str                    # caller-facing handle: prod, dev, backup
  priority: int = 100          # lower wins, ties by name
  enabled: bool = True
  version: int                 # bumped on rotation, this is the data plane cache-bust
  status: unknown | live | invalid | rate_limited   # advisory, written by event ingestion
  fingerprint: str             # last 4 characters, taken at write time, display only
  unique (workspace_id, provider_id, name)
  @audited
```

Rules that fall out:

- **No value column, ever.** The audit trigger copies before and after of every column, so a value
  column is a secret automatically written to a second table
- **No location column either.** The row's own fields are the `SecretRef`, so where the value lives
  is never something a tenant, an operator, or a migration writes down
- `name` is `api_immutable`: it is part of the ref a store may address a value by, so renaming would
  orphan the secret. Same standing as `Workspace.slug`
- `scope=platform` implies null org and workspace, instance owner only, enforced by a check
  constraint rather than guard code

Control-plane authority uses `provider-credentials.read` and `provider-credentials.manage`.

## Control plane write path

`POST /v1/orgs/{org}/workspaces/{ws}/provider-credentials` with `{provider, name, priority, value}`

1. Refuse up front unless the configured store is `writable`
2. Body carries plaintext once
3. Take the fingerprint
4. Insert the row so the credential id exists, then `store.put(ref, secret)`
5. Recompile the bundle

Rotate is `PUT .../{name}`: `put` against the same ref, bump `version`, same row, so the bundle diff
is one integer and every data plane refetches within one poll. Delete is `store.delete(ref)` then the
row.

Three hazards specific to this path:

- **FastAPI echoes invalid input in `detail`.** A validation error on the model holding the
  plaintext returns it to the caller and into access logs. The field is a redacting type, with a
  test that posts a malformed body and asserts the value is absent from the response
- **The row and the value are written in two systems.** A crash between them leaves a row whose
  value is missing, which reads as `SecretNotFoundError` at request time and is why that error skips
  a candidate rather than failing the tier. The reverse order would leave an orphan value with no
  row to delete it by, so the row goes first
- **Plaintext crosses the wire.** Refuse the endpoint over http outside local deployments, same
  proxy-scheme caveat already recorded for the session cookie

There is no write-time verification. A bad key surfaces on first use: the data plane fails over past
it, the usage event carries the failure, ingestion flips `status` to `invalid`, the console shows a
red key. Slower than a probe, but no adapter knowledge leaks into the control plane and there is no
outbound call on the write path.

## Security: who can write a credential

Whoever supplies a provider key owns the upstream account the organization's traffic is billed to,
and that account's dashboard can expose the prompts and completions sent through it. Credential
writes therefore use `provider-credentials.manage`, not a generic workspace write permission.

The [authority model](AUTHORITY.md) applies both a role grant and a credential ceiling at the
credential's actual tenant target:

- Organization owners and admins can manage organization credentials and credentials in their workspaces
- Workspace admins can manage credentials only in their workspace
- Workspace members and viewers can read credential metadata but cannot supply, rotate, disable, or delete values
- Organization members outside a workspace receive no credential access there
- Data-plane service accounts receive no provider-credential permission

Access keys always store an explicit permission ceiling. Adding a future permission cannot expand an
existing key, and role changes take effect without reminting it. Workspace targets resolve through
the workspace's organization-owned identity before authorization, so a credential cannot cross an
organization scope by naming a workspace id from another tenant.

## Bundle contract

```python
class CredentialEntry(BaseModel):  # frozen
    ref: SecretRef  # names the credential; carries no location and no secret
    priority: int
    version: int


class Catalog:
    providers: list[ProviderEntry]
    models: list[ModelEntry]
    credentials: list[CredentialEntry]
```

`ProviderEntry.credential_ref` is removed, so the catalog says how to reach a provider and the
credentials say how to authenticate to it. `UsageEventV1` gains `credential_id: UUID | None` and
`credential_scope`, which buys per-key attribution, rate-limit visibility, and the BYOK versus
platform billing split. `UsageStatus` gains `credential_rejected` and `rate_limited`, split out of
`upstream_error` because they are facts about the credential rather than about the provider.

That split is the whole feedback channel. The data plane never tells the control plane anything
about a credential; the usage events it already sends carry a key's health home, and ingestion
rolls them into `ProviderCredential.status`. `status_at` is what makes it safe: delivery is
at-least-once, so events replay after an outage and arrive out of order, and an older observation
must never flip a working key back to invalid. A provider outage leaves the status alone, and events
naming a credential that has since been deleted are skipped rather than treated as an error.

The deploy is lockstep. Add a `contract_version` check so a mismatch logs loudly at bundle admission
instead of manifesting as a data plane silently serving a week-old bundle forever: `verify_bundle`
re-serializes the payload, so an older data plane drops the unknown field and rejects every new
bundle without saying why.

## Data plane read path

`BundleSnapshot` already builds `key_index` at admit time; the credential index follows that idiom
rather than indexing per request.

```python
@dataclass(frozen=True)
class BundleSnapshot:
    bundle: BundleV1
    key_index: dict[str, KeyEntry]
    credential_index: dict[tuple[UUID | None, str], tuple[CredentialEntry, ...]]  # pre-sorted by priority, name
```

`evaluate(req, key, snap, now)` stays pure, synchronous and small, and returns the candidate set
rather than a choice:

```python
Allow(model, provider, candidates: tuple[CredentialEntry, ...])
```

Tier choice is three dict lookups taking the first non-empty of workspace, org, platform. An empty
result is `Deny("credential_unavailable", 402)`.

Selection is impure by nature, so it lives in `app.py` beside the resolver, never in `evaluate()`.
Failover only:

- candidates in priority order, skipping any in cooldown
- 401 or 403 marks the credential invalid and cools it down for 15 minutes, then advances
- 429 cools down for `max(Retry-After, 60s)`, then advances
- 5xx and timeouts do not advance: that is the provider, not the key
- only before the first streamed byte, never mid-stream
- tier exhausted returns the last upstream error, never a broader tier
- cooldowns are in-memory and die with the process, which is correct because they are hints

Resolver cache, memory only:

- keyed by `(ref, version)`, so a rotation busts it with no invalidation message and no TTL wait
- TTL 5 minutes as a backstop for a value edited in the store behind the control plane's back
- single-flight per key, or a cold cache under load stampedes the store
- short negative cache on `SecretNotFoundError`, none on `SecretStoreUnavailableError`: absence is a
  fact about a credential, unavailability is a fact about infrastructure

`Secret` carries the value: no `__str__`, `__repr__` is `Secret(***)`, not serializable, `.reveal()`
is the only accessor. It never enters `Ctx`, `UsageEventV1`, or an exception message. Python cannot
zero the bytes and the docstring says so rather than implying otherwise.

## Adapter change

All adapters move together, one edit each plus the base:

- `ProviderAdapter.__init__(self, provider, credential: Secret)`
- `transform_request` reads `self.credential.reveal()`; `resolve_ref` leaves the adapter entirely
- `validate_environment` is dropped, since eager env validation is meaningless when credentials are
  per workspace and plural

Adapter tests are parameterized over the registry, so the conformance suite is one edit.

## Failure modes

| Condition | Behavior |
|---|---|
| No enabled credential in any tier | 402 `credential_unavailable`, metered as denied |
| Tier exhausted by 401 | 502, every candidate in that tier marked invalid |
| All candidates in cooldown | 429 carrying the soonest expiry as `Retry-After` |
| Store unreachable, cache warm | serve from cache, warn |
| Store unreachable, cache cold | 503 `credential_backend_unavailable`, never widen tier |
| Row in bundle, no value in the store | skip candidate, negative-cache briefly, `invalid` via the event loop |

The warm-cache row is the one deliberate choice of availability over freshness. A cold cache does
not widen tier, because an infrastructure failure must never move an org's spend onto the platform
account.

## Never-persisted, enforced by tests

- planted-value property test: compiled bundle JSON, the `bundle.payload` column, and the data plane
  disk cache contain no known secret string
- `Secret` survives `repr`, f-string, `logging`, `json.dumps`, and pydantic dump as a redaction
  marker
- a malformed credential POST returns a `detail` that does not contain the submitted value
- no `ProviderCredential` column is secret-shaped, and `audit_log` after add, rotate and delete
  contains no value

## Dev and test

- **Unit**: the `memory` store, control plane writes and data plane reads one instance, which works
  because tests run both in one process
- **Conformance**: one suite parameterized over every writable store, the way adapter tests are
  parameterized over the registry, so the facade is proved once rather than per backend
- **Dev**: the `file` store under a local root, or `env` for a first run with no setup
- **`airllm quickstart` needs no infrastructure**: `env` backend, one `scope=platform` credential
  reading the `OPENAI_API_KEY` the operator already has

## Milestones

Each lands its failing test in the same commit.

1. **Done.** `contract/secrets/`: `Secret`, `SecretRef`, `SecretPurpose`, the `SecretStore` facade, the
   per-backend config union, the `memory`, `file` and `env` backends, conformance suite. No wiring
2. **Done.** Control plane end to end: `ProviderCredential` model and migration, scopes, CRUD with
   store writes, and the bundle emitting `catalog.credentials`. Merged with what was milestone 4,
   because a credential resource without its value is not a resource: the create route has to write
   the store or there is nothing to test
3. **Done.** Data plane read path: `credential_index` on the snapshot, `evaluate()` returns
   candidates, resolver with cache and single-flight, adapters take an injected credential, first
   candidate only. `Provider.credential_ref` and `ProviderEntry.credential_ref` are gone, and the
   catalog refuses a body still carrying one rather than ignoring it
4. **Partly done.** `credential_id` and `credential_scope` on usage events, and `status` rolled up
   from event ingestion. Failover and cooldown are deferred, with them the live proof: a real
   request against a running data plane where the first key is revoked mid-test and the request
   still succeeds on the second
5. Console and CLI: `airllm credentials add/list/rotate/rm --workspace --provider --name` with
   `--from-stdin` so keys never enter shell history, status and fingerprint columns, console panel
   with per-key health
6. The Vault KV v2 store: one module behind the facade, its own config fields, and its auth method
   in both plane configs

## Deferred to the next version

Parked in [notes/IDEAS.md](../IDEAS.md): credential policy, inference-key-to-credential binding,
caller-chosen key by header, per-workspace `base_url`.

## Open

Vault auth method for each plane, once milestone 7 comes up. AppRole is the portable default,
Kubernetes service account if we deploy there. It shapes both plane configs and nothing before
milestone 7 depends on it.
