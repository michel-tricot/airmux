# Workspace policies

Workspace policies control which inference requests AirLLM accepts, which models and credentials it
may use, and when it retries with a fallback model. Open **Policies** from a workspace in the
console to create, edit, reorder, enable, or disable them.

Policy management has two reusable levels:

- **Applies to** selects every inference key in the workspace or a fixed set of keys
- **Shared rules** each own a request match and action
- **Policies** reference an ordered collection of shared rules

Each rule's **Applies when** matches every request or requests with selected models, capabilities,
or streaming mode. Its **Action** defines the restriction or fallback behavior. A rule can be used by
multiple policies. Editing it updates every policy that references it, and a referenced rule cannot
be deleted.

All matching rules across all targeted policies compose, and every matching restriction must pass.
Rules run in their listed order. Lower policy priority numbers run first. Reordering policies in the
console updates their priorities. Priority affects evaluation order, but it cannot make a request
bypass another matching restriction. The first matching fallback policy supplies the fallback plan.

Policy changes take effect after the gateway adopts the workspace's updated configuration. This is
normally quick, but it is not synchronous with saving the policy.

## Targets and request matching

Choose **All keys** to include current and future inference keys as well as playground sessions.
Choose **Selected keys** to limit the policy to named inference keys. A selected-key policy does not
automatically include keys created later.

The request matcher can select one or more of these criteria:

| Criterion | A request matches when |
| --- | --- |
| Models | The caller's original requested model is in the list |
| Streaming | The caller requested the selected streaming mode |
| Capabilities | The request needs every selected capability: tools, reasoning, or structured output |

When a matcher contains several criteria, all of them must match. Matching always uses the original
request. A fallback attempt cannot escape a restriction by changing the model.

For example, create this shared rule to match streaming requests for `openai/gpt-4o` that use tools:

```json
{
  "name": "Team credentials for streaming tools",
  "definition": {
    "match": {
        "kind": "request",
        "models": ["openai/gpt-4o"],
        "stream": true,
        "capabilities": ["tools"]
    },
    "action": {
        "kind": "credential_access",
        "scopes": ["workspace", "org"]
    }
  }
}
```

Then attach its returned ID to one or more policies with `"rule_ids": ["RULE_ID"]`.

## Common use cases

### Limit output from a public feature

Suppose a public summarization endpoint should never generate more than 1,024 tokens. Give that
feature its own inference key, replace `PUBLIC_SUMMARIZER_KEY_ID` below with the key's ID, then
create this policy:

```json
{
  "name": "Public summaries stay short",
  "enabled": true,
  "priority": 10,
  "definition": {
    "target": {
      "kind": "selected_keys",
      "key_ids": ["PUBLIC_SUMMARIZER_KEY_ID"]
    },
    "rule_ids": ["PUBLIC_OUTPUT_LIMIT_RULE_ID"]
  }
}
```

A request from another inference key is unaffected. A request from the selected key with
`max_tokens` set to 2,000 is rejected before AirLLM contacts a provider. Pair this with a model price
limit when you also need to restrict the catalog rates the feature can use.

### Keep sensitive workloads on team-owned credentials

Suppose requests that produce structured output may contain business data and must use provider
accounts owned by your organization. This policy excludes platform credentials for those requests:

```json
{
  "name": "Structured output uses our provider accounts",
  "enabled": true,
  "priority": 20,
  "definition": {
    "target": { "kind": "all_keys" },
    "rule_ids": ["TEAM_CREDENTIAL_RULE_ID"]
  }
}
```

AirLLM first looks for a workspace credential, then an organization credential. If neither exists,
the request is rejected rather than sent with a platform credential.

### Keep a customer-facing chat model available

Suppose an application normally uses `openai/gpt-4o`, but should move to another model when the
provider is throttled or unavailable:

```json
{
  "name": "Production chat fallback",
  "enabled": true,
  "priority": 30,
  "definition": {
    "target": { "kind": "all_keys" },
    "rule_ids": ["PRODUCTION_FALLBACK_RULE_ID"]
  }
}
```

AirLLM tries the backups in order after a configured failure. Each route must still satisfy the
workspace's model, provider, credential, price, and parameter policies. Invalid requests and policy
denials never trigger a fallback.

## Credential access

**Credential access** controls which credential scopes a matching request may use. Available scopes
are `workspace`, `org`, and `platform`. To require credentials managed by the team, allow workspace
and organization credentials while excluding platform credentials:

```json
{
  "kind": "credential_access",
  "scopes": ["workspace", "org"]
}
```

Multiple credential policies compose by intersection. After filtering, AirLLM selects the most
specific populated allowed tier in workspace, organization, platform order. If that tier's
credentials fail or are exhausted, it does not fall through to a broader tier.

## Allowed models

**Allowed models** restricts matching requests to an explicit list of catalog model names. This is
useful for production allowlists or for limiting a particular inference key to approved models.

```json
{
  "kind": "models",
  "names": ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4-5-20250929"]
}
```

Fallback models must also be in every matching model allowlist.

## Allowed providers

**Allowed providers** restricts matching requests to models served by selected providers.

```json
{
  "kind": "providers",
  "names": ["openai", "anthropic"]
}
```

This policy applies to both the original route and fallback routes.

## Require parameter support

**Require parameter support** rejects a route if AirLLM would otherwise remove a supplied request
parameter because the destination model or provider does not support it.

```json
{ "kind": "strict_parameters" }
```

For example, if a caller explicitly sets `temperature` and the selected model does not support that
parameter, AirLLM returns a policy denial instead of silently omitting `temperature`. The same check
applies to provider-specific extra parameters. Model capability and input-modality validation always
runs whether or not this policy is enabled.

## Model price limit

**Model price limit** rejects catalog models whose published input or output price exceeds the
configured ceiling. Prices are USD per one million tokens.

```json
{
  "kind": "price_limit",
  "max_input_price_per_mtok": "2.50",
  "max_output_price_per_mtok": "10.00"
}
```

Both limits must pass. The policy checks static catalog rates for every primary and fallback model.
It does not predict or cap the total cost of a request.

## Request limits

**Request limits** caps the number of output tokens a caller may request.

```json
{
  "kind": "request_limits",
  "max_output_tokens": 4096
}
```

A request with a larger explicit output limit is rejected before an upstream request starts. A
request that omits its output limit is allowed because the gateway does not invent a caller limit.

## Deny matching requests

**Deny matching requests** rejects every request matched by the policy and returns the configured
message.

```json
{
  "kind": "deny",
  "message": "Reasoning models are not approved for this workspace"
}
```

This works well for temporary maintenance windows or blocking a capability for selected keys.

## Model fallbacks

**Model fallbacks** supplies an ordered list of backup models for selected upstream failures.

```json
{
  "kind": "fallback",
  "models": [
    "anthropic/claude-sonnet-4-5-20250929",
    "openai/gpt-4o-mini"
  ],
  "on": ["rate_limited", "upstream_unavailable", "timeout"],
  "max_attempts": 3,
  "timeout_ms": 30000
}
```

Supported failure reasons are:

| Reason | Trigger |
| --- | --- |
| `rate_limited` | The upstream returns HTTP 429 |
| `upstream_unavailable` | The upstream returns HTTP 5xx or cannot be reached |
| `timeout` | The upstream request exceeds the configured HTTP deadline |

The primary route must pass every restriction. AirLLM skips fallback routes that fail a model,
provider, credential, capability, or parameter restriction. Authentication failures do not trigger
model fallback by themselves.

`max_attempts` counts the primary call and credential retries, with a maximum of five total attempts.
The policy can contain up to four fallback models. `timeout_ms` covers secret resolution and all
attempts until response headers arrive. For streaming responses, it does not limit the duration of
the stream after those headers arrive.

A timeout can leave generation running at the provider even though AirLLM starts another attempt.
AirLLM records a separate usage event for every upstream attempt, using estimated usage when final
provider usage is unavailable. Fallback therefore does not provide exactly-once generation.

## Budget

**Budget** records a daily or monthly spending policy for either the workspace as a whole or each
targeted inference key.

```json
{
  "kind": "budget",
  "period": "month",
  "amount_usd": "250.00",
  "sharing": "shared"
}
```

Budget enforcement is not implemented yet. Saving or enabling this policy does not limit spending.

## Complete API example

The rule API is available at `/api/v1/orgs/{org_id}/workspaces/{workspace_ref}/rules`. Create each
reusable restriction first:

```json
{
  "name": "Approved production pricing",
  "definition": {
    "match": { "kind": "all_requests" },
    "action": {
      "kind": "price_limit",
      "max_input_price_per_mtok": "2.50",
      "max_output_price_per_mtok": "10.00"
    }
  }
}
```

The policy API is available at `/api/v1/orgs/{org_id}/workspaces/{workspace_ref}/policies`. Attach the
returned rule IDs in evaluation order:

```json
{
  "name": "Approved production routing",
  "enabled": true,
  "priority": 20,
  "definition": {
    "target": { "kind": "all_keys" },
    "rule_ids": ["PRICE_LIMIT_RULE_ID", "APPROVED_MODELS_RULE_ID"]
  }
}
```

The CLI accepts the same JSON shape:

```sh
airllm policies list -w production -f table
airllm rules create rule.json -w production
airllm policies create policy.json -w production
airllm policies update POLICY_ID changes.json -w production
airllm policies delete POLICY_ID -w production
```
