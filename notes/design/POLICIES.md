# Workspace inference policies

Policies belong to one workspace. There is no organization policy inheritance in this version.
An enabled policy targets all keys, including future keys and playground sessions, or an explicit
set of inference keys in that workspace. Disabled policies are stored but excluded from bundles.

## Contract and execution

Each policy has a name, priority, target, typed request match, and one typed action. Separate
policies compose restrictions: every matching restriction must pass. Lower priorities run first;
policy UUID breaks ties. Priority cannot override a restriction. The first matching fallback
policy supplies the ordered backup list.

The control plane validates request matches and references when saving. Its existing transaction
publication mechanism includes policies in the organization's bundle. The data plane compiles
matches when admitting a bundle, indexes them by workspace, and keeps the previous bundle if
admission fails. In-flight requests use their original snapshot. Changes take effect after the
gateway adopts the published bundle, not synchronously with the management response.

`@bundle_input` marks models and columns whose changes require bundle republication. Its scope
identifies affected bundles, not the enforcement scope of a policy. `Policy.save()` owns the
workspace row lock, match/reference validation, active-policy capacity check, and flush.
Autoflush is suppressed until validation finishes, and capacity is counted directly in the
database so previously loaded policy objects cannot hide a concurrent activation. Callers do
not acquire a separate lock or invoke validation themselves.

Evaluation uses the canonical request. It is synchronous, deterministic, and has no database,
network, clock, or secret-store access. Credential resolution and upstream execution remain
outside evaluation. Request matching cannot select credentials, issue requests, or mutate state.

## Request matching

A policy either matches every request or supplies request criteria. Every supplied criterion must
match. Empty request matches and duplicate values are invalid.

| Criterion | Type | Meaning |
| --- | --- | --- |
| `models` | list of catalog model names | Original caller-requested model must be listed |
| `stream` | boolean | Caller must request the configured response mode |
| `capabilities` | list of capabilities | Request must require every listed capability |

Capabilities are `tools`, `reasoning`, and `structured_output`; streaming has its own criterion.
A workspace may have at most 100 active policies; management writes serialize on the workspace
to enforce this bound.
Bundle admission independently checks it. Matches are evaluated once against the original request.
The same matched restrictions apply to every backup, so changing the route cannot escape a guardrail.

## Actions

| Kind | Configuration | Behavior |
| --- | --- | --- |
| `byok` | None | Excludes platform credentials; permits the caller's organization and workspace credentials |
| `models` | `names` | Allows only listed catalog model names |
| `providers` | `names` | Allows only listed provider names |
| `deny` | `message` | Rejects matching requests with a configured explanation |
| `strict_parameters` | None | Rejects a route when reconciliation would drop a supplied parameter |
| `price_limit` | input and output USD per million token ceilings | Rejects catalog models whose rates exceed either ceiling |
| `request_limits` | maximum requested output tokens | Rejects requests above the configured output bound |
| `credential_access` | allowed credential scopes | Filters credentials to workspace, organization, or platform scopes before tier selection |
| `fallback` | `models`, `on`, `max_attempts`, `timeout_ms` | Supplies an ordered, bounded backup plan |
| `budget` | `period`, `amount_usd`, `sharing` | Stores intent only; does not track or enforce spending |

Budget periods are `day` and `month`. Sharing is `shared` or `per_key`. Amounts use decimal USD,
not floating-point arithmetic. Enabling a budget policy does not activate a spending limit. The
console explains that enforcement is not available yet.

Price limits compare the static input and output rates published in the bundle. They do not predict
or cap the total cost of one request. Strict parameter support covers parameters reconciliation
would otherwise drop; model capability and input-modality checks remain unconditional route checks.

Credential access policies compose by intersection. After filtering, the evaluator selects the
most specific populated allowed tier in workspace, organization, platform order. Exhausting or
rejecting credentials in that selected tier does not fall through to a broader tier.

## Fallback semantics

The original route must pass restrictions and capability checks. A policy denial, unknown
primary model, or invalid request does not trigger fallback. Backup routes must independently
pass capability, credential-scope, BYOK, model, and provider restrictions. Ineligible backups
are skipped. Backup request matches are not reevaluated and fallback policies do not recurse.

Failure reasons are `rate_limited` (429), `upstream_unavailable` (5xx or connection failure),
and `timeout` (upstream HTTP timeout). Credential retries on 401, 403, and 429 remain available
within a route. Authentication errors do not by themselves trigger model fallback. There is
no backoff or same-credential retry loop in this version.

At most four backup models and five total upstream attempts are allowed. `max_attempts` counts
the primary call and credential retries. `timeout_ms` bounds the whole pre-response execution,
including secret resolution and all attempts, from 100 ms to 120 seconds. For streaming this
deadline ends when successful upstream response headers are handed off. It does not cap stream
duration. Once handed off, stream errors are rendered in-stream and never restart generation.
Timeouts can leave work running at an upstream provider, so fallback is not an exactly-once
guarantee.

Each upstream attempt produces its own usage event with the shared request ID and actual
model, provider, and credential. Cancellation uses estimated usage when provider usage is not
available. A deadline returns 504; if no eligible backup succeeds, the last attempt's error is
returned. Policy denials produce the existing denied usage event without an upstream request.

## Management

The console exposes **Policies** in the workspace sidebar. Workspace admins and organization
admins/owners can manage policies. Workspace members and viewers can read them. Access keys
need `policies.read` or `policies.manage` within their existing authority scope. Every write is
covered by database audit triggers.

The API resource is `/api/v1/orgs/{org_id}/workspaces/{workspace_ref}/policies`, supporting list,
create, patch, and delete. Successful responses use the standard envelope. Create example:

```json
{
  "name": "Production fallback",
  "enabled": true,
  "priority": 100,
  "definition": {
    "target": { "kind": "all_keys" },
    "match": { "kind": "request", "models": ["primary-model"] },
    "action": {
      "kind": "fallback",
      "models": ["backup-model", "second-backup"],
      "on": ["rate_limited", "upstream_unavailable", "timeout"],
      "max_attempts": 3,
      "timeout_ms": 30000
    }
  }
}
```

Names must exist in the catalog. To target specific keys, replace `target` with
`{"kind": "selected_keys", "key_ids": ["inference-key-uuid"]}`.
PATCH replaces `definition` as a whole; omitted fields are unchanged and explicit nulls are
rejected. CLI commands use the same generated request and response types:

```sh
airllm policies list -w production -f json
airllm policies create policy.json -w production
airllm policies update POLICY_ID changes.json -w production
airllm policies delete POLICY_ID -w production
```

## Performance and extension

Local CPython 3.13.7 ARM64 measurement: 10,000 warm `plan_routes` calls after 1,000 warmups,
with matching typed model and non-streaming request criteria, model restrictions, and one
credential. Bundle index construction, network traffic, and concurrent load are excluded.

| Policies | Median | p99 |
| --- | --- | --- |
| 0 | 3.21 us | 4.29 us |
| 10 | 10.88 us | 14.38 us |
| 50 | 42.29 us | 60.04 us |
| 100 | 82.75 us | 117.42 us |

These are development measurements, not service guarantees. Longer lists need their own benchmarks.

To extend the system, add a strict action variant to `PolicyAction`, then add its evaluator module
under `data_plane.policy_actions`. Evaluator modules register themselves and are discovered without
editing a dispatcher. Add UI support, regenerate clients, and test both normal enforcement and interaction with fallback.
Real budgets will require atomic reservation and reconciliation outside `evaluate()`, with
explicit concurrency, period-boundary, failure, and multi-instance semantics before enforcement
can be enabled.
