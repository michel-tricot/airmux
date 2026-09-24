# Public release security audit

Reviewed base commit: `123a31b336da086212f445b176cefc3f44c74b33` on 2026-09-23

This review covers the all-in-one and split full-platform deployments, the native and container gateway-only deployments, and the build and release path. It is a point-in-time assessment, not a claim that the project has no other vulnerabilities. No production system or paid provider was tested.

## Threat model

| Actor | Entry point and authority | Assets crossing the boundary |
| --- | --- | --- |
| Anonymous network client | Signup, login, invitation preview, CLI authorization start, and public health endpoints | First-owner authority, account identities, password verification capacity |
| Browser session | Console through `/api/v1` and playground cookie through `/inf/` | Management changes, provider credentials, scoped usage and audit records |
| Management-key holder | `/api/v1` with a scoped bearer credential | Organization and workspace resources, bundle reads, usage ingestion, key delegation |
| Inference-key holder | Public inference and model discovery routes | Provider calls, spending, workspace policy, gateway memory and connection pool |
| Instance catalog administrator | Provider and model configuration | Provider destination and the credential sent to that destination |
| Gateway process | Authenticated bundle, budget, heartbeat, and usage traffic with the control plane; secret-store reads | Token hashes, policy snapshots, provider values, durable usage queue |
| Provider or network peer | Upstream HTTP and SSE responses | Untrusted response bytes entering parsers and metering |
| Local host user or CI contributor | State volumes, checkout history, build and release inputs | Cached bundle and usage metadata, historical secrets, release artifacts |

The main boundaries are browser to public proxy, proxy to management and inference processes, authenticated gateway to control plane, gateway to secret store, gateway to provider, and CI source to published artifacts. In gateway-only mode, local files replace the management and database boundaries but the public inference and provider boundaries remain.

## Release decision

Do not publish yet. The owner claim window, budget enforcement, and stale-key behavior need fixes or explicit maintainer risk decisions. Historical signing material needs a private disposition before repository history becomes public. Per-key traffic protection and payload bounds should land before a multi-tenant deployment is exposed.

| Priority | Finding or decision | Work | Disposition |
| --- | --- | --- | --- |
| High | The first successful public signup on a fresh instance becomes its owner even with public signup disabled | [#338](https://github.com/michel-tricot/airmux/issues/338) | Release blocker pending a protected claim or explicit acceptance of a private bootstrap requirement |
| High | Budget checks allow requests when state is missing, mismatched, or expired, and concurrent gateways do not reserve shared spend atomically | [#211](https://github.com/michel-tricot/airmux/issues/211) | Release blocker for any claim of spending enforcement |
| High | Cached bundles can authorize a revoked nonexpiring key for the full duration of a control-plane outage | [#342](https://github.com/michel-tricot/airmux/issues/342) | Release blocker pending a maximum-staleness decision or explicit acceptance |
| High, conditional | A PEM private key exists in earlier repository history; current use was not found | [#341](https://github.com/michel-tricot/airmux/issues/341) | Maintainer must establish whether it was ever trusted and rotate or retire it before publication |
| Medium | One inference key can occupy the shared upstream pool without per-key rate or concurrency admission | [#217](https://github.com/michel-tricot/airmux/issues/217) | Fix before shared public service |
| Medium | Direct gateway requests and upstream buffered and streaming payloads lack application-level byte bounds | [#339](https://github.com/michel-tricot/airmux/issues/339) | Fix before public exposure of direct gateway mode |
| Medium | Native gateway state files are readable by other local users under a standard `022` umask | [#340](https://github.com/michel-tricot/airmux/issues/340) | Fix before recommending shared-host native deployment |
| Release gate | A private email contact is documented, but live GitHub security settings and private vulnerability reporting are not yet verified | [#343](https://github.com/michel-tricot/airmux/issues/343) | Verify after the repository visibility change |

## Evidence and attacker prerequisites

### Owner claim

`/api/v1/auth/signup` calls `User.reserve_unclaimed_instance()` before applying the `public_signup` restriction and grants `InstanceRole.owner` to the first account. The transaction lock prevents a double claim, but no operator-held secret is required. An attacker needs network access while an instance is unclaimed. Impact is full instance administration. The existing Postgres-backed auth tests confirm the first-signup behavior. A fix must reject an unauthenticated remote claim in a running control plane while preserving atomic ownership creation.

### Budgets and traffic

`BudgetStateHolder.check()` returns a fallback for absent, mismatched, and expired state, while `ControlPlaneBudgetBackend.check()` only records that fallback as a metric. `NoBudgetBackend` always allows. The focused test `test_uninitialized_budget_state_allows_matching_requests` passed and records the current behavior. A caller with an inference key can generate provider spend while state is unavailable or before delayed usage has reached the database. [#211](https://github.com/michel-tricot/airmux/issues/211) already specifies atomic reservation, settlement, and fail-closed behavior for budgeted attempts. The current data-plane request path also has no caller admission step; [#217](https://github.com/michel-tricot/airmux/issues/217) owns rate and concurrency protection. Both fixes need real requests against a running data plane, including concurrent gateways and cancellation.

### Revocation during outages

`RemoteBundleSource` adopts a cached bundle at startup and retains its last accepted snapshot when polling fails. `authenticate()` checks token membership in that snapshot and an optional key expiry, but has no maximum bundle age. An attacker needs a key that was valid before revocation and a gateway that cannot refresh. Impact is continued inference access and spend during the outage. The [bundle documentation](../../docs/concepts/bundles.mdx) describes the availability behavior. [#342](https://github.com/michel-tricot/airmux/issues/342) calls for an explicit maximum-staleness contract or recorded acceptance, with a live gateway regression test.

### Payload and state limits

The packaged Nginx proxy sets a 32 MiB client-body limit, but standalone `complete()` reads `request.body()` without a limit. A 33 MiB invalid JSON request sent to an isolated running gateway returned a normal `400` parse error and left the process alive, showing that the direct request reached full buffering. The current PyReqwest wrapper reads complete buffered responses and streaming error responses without a byte ceiling; SSE framing also retains incomplete lines and accumulated content without a ceiling. An attacker needs an inference key for request-body abuse, while a faulty or attacker-controlled upstream can trigger the response path. The separate [#339](https://github.com/michel-tricot/airmux/issues/339) requires bounded real-request proof.

Under a `022` umask, a temporary native gateway state directory was created as `0755`; `instance_id`, `bundles.json`, and `events.db` were created as `0644`. A local user with access to the host can read bundle metadata and usage records. The packaged image initializes `/state/data-plane` privately, but native paths and user-provided mounts do not inherit that protection. [#340](https://github.com/michel-tricot/airmux/issues/340) requires mode tests under an unsafe umask and an existing mount.

### Historical signing material

A history-only PEM private-key artifact was found by enumerating paths across Git history and checking its file type without printing its contents. No current runtime reference to the old signing path was found. This does not prove the key was unused elsewhere. The maintainer must assess any former deployment or external trust in a restricted channel and record rotation or retirement in [#341](https://github.com/michel-tricot/airmux/issues/341) before making the repository public.

## Scope and coverage

| Area | Reviewed evidence | Remaining uncertainty |
| --- | --- | --- |
| Threat model | Mapped browser, CLI, management API, gateway, Postgres, file secret store, provider, and control-plane synchronization trust boundaries | External ingress and network policy vary by operator |
| Authentication | Reviewed signup, login, invitations, sessions, CLI authorization, management keys, inference keys, and service accounts; targeted Postgres tests passed | No external identity provider or production account lifecycle was tested |
| Authorization and tenancy | Reviewed scope decisions, org-owned lookups, bundle manifest and event ingestion checks, and reporting scope; targeted Postgres tests passed | A route-by-route manual penetration test against a deployed multi-tenant stack was not run |
| Browser | Reviewed cookie flags, requested-with and fetch-site checks, packaged CSP and cache headers, and SVG sanitization; console tests passed | No live cross-origin browser or full console UI audit was run |
| Secrets | Reviewed key hashes, secret references, file store, cache, outbox, response redaction, and Git path history | Backups, external logs, tracing exports, and historical key deployment need operator evidence |
| Gateway | Reviewed ingress and egress boundaries, URL configuration, header construction, redirects, parsing, streaming, fallback, and metering; local stub-provider acceptance passed | No hostile public provider or paid provider was tested; provider response limits remain open |
| Abuse and spending | Reviewed authentication throttling, per-key admission, token limits, retries, budgets, and durable outbox | No disruptive load or paid-provider stress test was run; disk exhaustion was assessed from code only |
| Internal protocol | Reviewed operational key permissions, scoped bundle reads, event validation and idempotency, heartbeat scope, and cached-bundle outage behavior | No active network attacker or long outage was simulated |
| Deployment and supply chain | Reviewed Compose listeners, image user, state mounts, CI permissions, pinned actions, release artifact digests, current tracked paths, and historical secret filenames; dependency audits passed | No container image CVE scan or complete historical secret-content scan was run; the live security-policy API did not confirm requested settings |
| Readiness | Reviewed deployment security and incident guidance; [SECURITY.md](../../SECURITY.md) now gives a private email contact | GitHub private vulnerability reporting and scanner settings still need launch verification; [#343](https://github.com/michel-tricot/airmux/issues/343) tracks it |

Provider base URLs are set through instance catalog management or local operator files, not by inference callers. A catalog administrator can direct provider credentials to an arbitrary HTTP endpoint. This is a privileged configuration capability and should be treated as such when delegating catalog permissions. The provider client does not enable automatic redirects in its construction; keep a regression test if that behavior changes.

The Compose files default to a development Postgres password while leaving the database off the host port. Production instructions require an operator-set password before database initialization. The audit did not treat this as a remotely reachable default exploit, but public deployment documentation must keep the setup requirement prominent. The packaged proxy provides CSP, response cache controls, and a request-body ceiling; direct processes and replacement proxies need equivalent edge controls. The runtime image uses an unprivileged user, while its base image tags are mutable until the resulting candidate is built and verified by digest.

The full-platform quickstart now binds Compose to loopback while the first owner claims the instance. The general Compose file still publishes its port on all host interfaces by default; operators using it outside the quickstart must restrict access before the owner claim or set an explicit bind address.

## Checks performed

- Python data-plane, runtime, and contract suite on the reviewed base: 1,091 passed, one skipped
- Selected real gateway acceptance suite on the reviewed base with local stub providers: 210 passed across basic, protocol, failure, and runtime scenarios
- Complete control-plane suite on the reviewed base, including Postgres integration: 522 passed
- CLI and model-audit suites on the reviewed base: 317 passed
- Console and API client unit suites on the reviewed base: 257 passed; workspace TypeScript typecheck passed
- Documentation and CI release-policy checks on the reviewed base: 198 passed
- Python typecheck: `ty check .` passed on the reviewed base
- `bun audit` on the reviewed base: no known vulnerabilities found
- Locked `pip-audit --strict --disable-pip --no-deps` on the reviewed base: no known vulnerabilities found
- Isolated real gateway request on the reviewed base: 33 MiB invalid JSON reached parsing and returned `400`; the process remained ready
- Temporary native state creation under `022`: directory `0755`, cache and outbox files `0644`
- Read-only live GitHub policy diff did not confirm the requested CodeQL, secret-scanning, and push-protection settings; plan or repository visibility may affect the API result
- Selected local full-stack account, invitation, offboarding, outage, and budget scenarios on the reviewed base: 11 passed
- `docker compose config` confirmed the quickstart override publishes port 8080 only on `127.0.0.1`

Dependency advisories and tests cannot establish absence of application vulnerabilities. The remaining release decisions and untested environments above stay open.
