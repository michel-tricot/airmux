# Workspace inference policies

Policies belong to one workspace. There is no organization policy inheritance in this version.
An enabled policy targets all keys, including future keys and playground sessions, or an explicit
set of inference keys in that workspace. Disabled policies are stored but excluded from bundles.

## Contract and execution

Each policy has a name, priority, target, boolean CEL condition, and one typed action. Separate
policies compose restrictions: every matching restriction must pass. Lower priorities run first;
policy UUID breaks ties. Priority cannot override a restriction. The first matching fallback
policy supplies the ordered backup list.

The control plane validates conditions and references when saving. Its existing transaction
publication mechanism includes policies in the organization's bundle. The data plane compiles
conditions when admitting a bundle, indexes them by workspace, and keeps the previous bundle if
admission fails. In-flight requests use their original snapshot. Changes take effect after the
gateway adopts the published bundle, not synchronously with the management response.

Evaluation uses the canonical request. It is synchronous, deterministic, and has no database,
network, clock, or secret-store access. Credential resolution and upstream execution remain
outside evaluation. CEL cannot select credentials, issue requests, or mutate state.

## Conditions

Conditions are compiled with `cel-expr-python==0.1.3`, the native CEL implementation's Python
binding. This dependency is pinned and hidden behind the contract's condition compiler. Its
wheel availability is a deployment constraint: the locked Python 3.13/3.14 releases include
macOS and glibc Linux x86-64/ARM64, but not musl Linux.

Available variables:

| Variable | Type | Meaning |
| --- | --- | --- |
| `request_model` | string | Original caller-requested catalog model name |
| `request_stream` | bool | Whether the caller requested streaming |
| `key_id` | string | Authenticated inference key or playground session identifier |
| `workspace_id` | string | Authenticated workspace UUID |

For example, `request_model.startsWith("gpt-") && !request_stream`.
Use `true` for an unconditional policy. Conditions are limited to 2,048 characters and must
type-check to a boolean. Comprehension macros (`all`, `exists`, `exists_one`, `map`, `filter`)
are disabled. A workspace may have at most 100 active policies; management writes serialize on
the workspace to enforce this bound. Bundle admission independently checks it.

An evaluation error in an enforcing policy denies the request with `policy_error`. All
conditions are evaluated once against the original request. The same matched restrictions
apply to every backup, so changing the route cannot escape a conditional guardrail.

## Actions

| Kind | Configuration | Behavior |
| --- | --- | --- |
| `byok` | None | Excludes platform credentials; permits the caller's organization and workspace credentials |
| `models` | `names` | Allows only listed catalog model names |
| `providers` | `names` | Allows only listed provider names |
| `deny` | `message` | Rejects matching requests with a configured explanation |
| `fallback` | `models`, `on`, `max_attempts`, `timeout_ms` | Supplies an ordered, bounded backup plan |
| `budget` | `enforcement: placeholder`, `period`, `amount_usd`, `sharing` | Stores intent only; does not track or enforce spending |

Budget periods are `day` and `month`. Sharing is `shared` or `per_key`. Amounts use decimal USD,
not floating-point arithmetic. Even a budget condition that would fail at runtime cannot affect
requests. Enabling a budget policy does not activate a spending limit. The console labels it
as a placeholder and the API requires the explicit placeholder enforcement value.

## Fallback semantics

The original route must pass restrictions and capability checks. A policy denial, unknown
primary model, or invalid request does not trigger fallback. Backup routes must independently
pass capability, credential-scope, BYOK, model, and provider restrictions. Ineligible backups
are skipped. Backup conditions are not reevaluated and fallback policies do not recurse.

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
    "condition": "request_model == 'primary-model'",
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
with matching `request_model.startsWith("gpt") && !request_stream` model restrictions and one
credential. Compilation, network traffic, and concurrent load are excluded.

| Policies | Median | p99 |
| --- | --- | --- |
| 0 | 2.88 us | 3.75 us |
| 10 | 23.38 us | 31.21 us |
| 50 | 92.92 us | 140.33 us |
| 100 | 189.50 us | 278.67 us |

These are development measurements, not service guarantees. More expensive expressions and
longer lists need their own benchmarks.

To extend the system, add a strict action variant to `PolicyAction`, validate its configuration,
and implement its pure decision or executor behavior. Add UI support, regenerate clients, and
test both normal enforcement and interaction with fallback. Keep CEL limited to matching.
Real budgets will require atomic reservation and reconciliation outside `evaluate()`, with
explicit concurrency, period-boundary, failure, and multi-instance semantics before enforcement
can be enabled.
