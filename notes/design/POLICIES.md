# Workspace inference policies

Policies belong to one workspace. There is no organization policy inheritance in this version.
An enabled policy targets all keys, including future keys and playground sessions, or an explicit
set of inference keys in that workspace. Disabled policies are stored but excluded from bundles.

## Contract and execution

Each policy has a name, target, and an unordered nonempty collection of rules. Each rule has
a typed request match and one typed action. Rules are inline values with no identity or lifecycle outside their policy. They compose within and across policies:
every matching restriction must pass. Policies are traversed by UUID for deterministic evaluation.
A policy may contain at most one fallback rule, and the first matching policy with one supplies the
ordered backup list.

The control plane validates request matches and catalog names when saving. Its existing transaction
publication mechanism includes policies in the organization's bundle. The data plane compiles
matches when admitting a bundle, indexes them by workspace, and keeps the previous bundle if
admission fails. In-flight requests use their original routing snapshot. Routing restrictions take
effect after the gateway adopts the published bundle. Budget restrictions use their independently
polled state described below. Neither takes effect synchronously with the management response.

`@bundle_input` marks models whose changes require bundle republication. Its scope identifies
affected bundles, not the enforcement scope of a policy. `Policy.save()` owns the
workspace row lock, match and action validation, active-policy capacity check, and flush.
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
A workspace may have at most 100 active rules across its enabled policies; management writes
serialize on the workspace to enforce this bound.
Bundle admission independently checks it. Matches are evaluated once against the original request.
The same matched restrictions apply to every backup, so changing the route cannot escape a guardrail.

## Actions

| Kind | Configuration | Behavior |
| --- | --- | --- |
| `models` | `names` | Allows only listed catalog model names |
| `providers` | `names` | Allows only listed provider names |
| `deny` | `message` | Rejects matching requests with a configured explanation |
| `strict_parameters` | None | Rejects a route when reconciliation would drop a supplied parameter |
| `price_limit` | input and output USD per million token ceilings | Rejects catalog models whose rates exceed either ceiling |
| `request_limits` | maximum requested output tokens | Rejects requests above the configured output bound |
| `budget` | `amount_usd`, `period`, `aggregation` | Rejects requests after observed spending reaches the allowance |
| `credential_access` | allowed credential scopes | Filters credentials to workspace, organization, or platform scopes before tier selection |
| `fallback` | `models`, `on`, `max_attempts`, `timeout_ms` | Supplies an ordered, bounded backup plan |

Price limits compare the static input and output rates published in the bundle. They do not predict
or cap the total cost of one request. Strict parameter support covers parameters reconciliation
would otherwise drop; model capability and input-modality checks remain unconditional route checks.

Credential access policies compose by intersection. After filtering, the evaluator selects the
most specific populated allowed tier in workspace, organization, platform order. Exhausting or
rejecting credentials in that selected tier does not fall through to a broader tier.

## Fallback semantics

The original route must pass restrictions and capability checks. A policy denial, unknown
primary model, or invalid request does not trigger fallback. Backup routes must independently
pass capability, credential-scope, model, and provider restrictions. Ineligible backups
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
admins/owners can manage policies. Workspace members and viewers can read them. Management keys
need `policies.read` or `policies.manage` within their existing authority scope. Every write is
covered by database audit triggers.

Rule definitions are stored inline in each policy. Explicit duplication is intentional: a restriction has meaning only within
the policy that names and targets it, and copying the value avoids hidden cross-policy mutation, reference validation, orphaned
rules, and a second permission and lifecycle surface. If repeated construction becomes a demonstrated problem, add an explicit
copy operation rather than shared mutable enforcement.

The policy API is `/api/v1/organizations/{org_id}/workspaces/{workspace_ref}/policies`, supporting list,
create, patch, and delete. Successful responses use the standard envelope. Create example:

```json
{
  "name": "Production fallback",
  "enabled": true,
  "definition": {
    "target": { "kind": "workspace" },
    "rules": [
      {
        "match": { "kind": "all_requests" },
        "action": {
          "kind": "fallback",
          "models": ["anthropic/claude-sonnet-4-6"],
          "on": ["timeout"],
          "max_attempts": 2,
          "timeout_ms": 30000
        }
      }
    ]
  }
}
```

Names must exist in the catalog. To target specific keys, replace `target` with
`{"kind": "selected_keys", "key_ids": ["inference-key-uuid"]}`.
PATCH replaces `definition` as a whole; omitted fields are unchanged and explicit nulls are
rejected. CLI commands use the same generated request and response types:

```sh
airmux policies list -w production -f json
airmux policies create policy.json -w production
airmux policies update POLICY_ID changes.json -w production
airmux policies delete POLICY_ID -w production
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

## Historical cost budgets

`budget` actions contain a positive exact `amount_usd`, a UTC calendar `period` (`day` or `month`),
and `aggregation` (`shared` or `per_key`). The policy target determines whether the rule applies to a workspace,
selected users, or selected inference keys. Multiple budget rules per policy are supported. Every matching
budget must permit an attempt, including credential retries and fallbacks; active attempts finish normally.

Usage facts own spending. Budget accounting sums `usage_event.cost_usd` within the completion-time window,
organization, workspace, target, and original request filter. It never filters by policy or bundle identity.
Creating a budget counts earlier matching usage; deleting, recreating, moving, disabling, or editing one cannot
reset the history. Recorded prices are not recalculated. Event IDs deduplicate repeated delivery;
separate provider attempts each contribute cost.

Events retain the original `user_id`, `requested_model_id`, and `requested_capabilities` independently of the
routed model and active policies. These facts survive key deletion, fallback, and reconciliation. Keep history
for the longest supported active window, including when no policy exists. Missing old request facts are not backfilled.

The first implementation uses indexed SQL aggregates over usage events, with no counter table,
reservation authority, distributed cache, or per-request network operation. Operational results use
aggregation-specific SQL grouping and HAVING to return exhausted buckets; management results use keyset pagination. If scans become
expensive, fact-based rollups can preserve these semantics without tying spend to policy identity.

Budget state is pulled independently from bundles through the control plane's Data Plane API. The response
carries each rule's target, match, allowance, window, and exhaustion state together. Policy ID and canonical
rule index describe the source configuration for inspection; neither is an accounting identity. The data plane
indexes these snapshots by organization, workspace, and source rule and atomically replaces its in-memory state.
At evaluation, the budget definition in state must match the rule in the active bundle. A mismatch fails closed
until the independently polled bundle and budget state agree.

The management status endpoint returns the evaluated policy definition and one result per budget rule.
It requires both policy and usage read permission. Disabled policies still have observable historical spend.
