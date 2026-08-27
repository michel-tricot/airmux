# Taxonomy maintenance

This directory contains the provider catalog, normalized model catalogs, and the applied taxonomy consumed by AirLLM. Use the root `airllm-audit` CLI for maintenance. Run every command below from the repository root.

## Choose the workflow

| Goal | Command |
| --- | --- |
| Add a provider and derive its catalog | `uv run airllm-audit providers add provider.yml` |
| Refresh schemas and models for one provider | `uv run airllm-audit providers refresh <provider>` |
| Backfill every listed model for one provider | `uv run airllm-audit models refresh <provider>` |
| Add one model | `uv run airllm-audit models add <provider> <model> --source <vendor-url>` |
| Update one model | Add it again with authoritative values and `--replace` |
| Measure model behavior | `uv run airllm-audit runs execute ...` followed by `evidence accept` |
| Regenerate derived taxonomy | `uv run airllm-audit taxonomy build` |
| Validate the complete taxonomy | `uv run airllm-audit taxonomy validate` |

Plan a live audit before executing it, and validate before and after every maintenance change:

```bash
uv run airllm-audit cases coverage
uv run airllm-audit taxonomy validate
```

## Skill versus CLI

The `provider-catalog` skill and `airllm-audit` CLI have different jobs. The skill gives an agent the maintenance rules, research standards, evidence boundaries, and decision process. The CLI performs the deterministic repository changes, live experiments, generation, and validation.

Use the CLI alone when the operation and source are already understood:

- List providers, models, cases, evidence, or planned experiments
- Refresh a known provider or its model catalog
- Add or replace a model from an already verified vendor source
- Build or validate generated taxonomy
- Run an already defined audit matrix
- Use the same commands from CI or a human-operated terminal

Use the skill when an agent needs judgment or research:

- Decide whether a fact belongs in provider metadata, model metadata, an audit case, or accepted evidence
- Research current provider endpoints, authentication, models, limits, prices, schemas, or supported features
- Interpret ambiguous refresh output, unknown behavior, harness failures, or gateway gaps
- Design a new capability, option, modality, interaction, or semantic oracle
- Determine whether a provider needs a custom source adapter
- Review whether evidence is authoritative enough to promote

Use both for non-routine maintenance:

1. Invoke the `provider-catalog` skill so the agent applies the catalog and evidence rules
2. Verify unstable facts against vendor-owned sources
3. Use `airllm-audit` to make, plan, execute, generate, and validate the change
4. Review the resulting diff and live report before accepting evidence

The skill is not an alternate taxonomy generator, and its legacy scripts must not be run. The CLI remains the execution path even when the skill is active. A human following a known workflow does not need the skill; an agent modifying or interpreting the catalog should use it.

## Know which files own which facts

| Path | Purpose | Maintenance rule |
| --- | --- | --- |
| `providers.yml` | Provider identity, endpoints, authentication, schemas, and supported direct API surfaces | Manage with `providers add`; commit changes |
| `models/<provider>.json` | Provider-listed or manually sourced model metadata | Manage with `models refresh` or `models add`; commit changes |
| `icons/` | Provider presentation | Provider setup creates a placeholder when needed; review or replace it and commit |
| Provider schemas | Machine-readable API shapes | Derived during provider setup and provider refresh; inspect and commit |
| `../model-audit/definitions/features.yml` | Finite vocabulary of capabilities, options, modalities, interactions, and behaviors | Edit when introducing a new taxonomy concept |
| `../model-audit/cases/` | Executable direct-provider versus gateway experiments | Add or update cases when behavior coverage changes |
| `../model-audit/evidence/accepted.json` | Deliberately promoted direct API observations | Change only through `evidence accept` |
| `behavior.json` | Behavioral projection of accepted evidence | Generated; never edit directly |
| `taxonomy.yml` | Applied routing taxonomy consumed by AirLLM | Generated; never edit directly |
| `../model-audit/reports/` | Transient audit reports and gateway-gap diagnostics | Inspect locally; do not treat as accepted evidence |

Declared provider metadata and observed behavior are different evidence sources. Provider listing responses and vendor documentation belong in the provider and model catalogs. Live behavior belongs in accepted audit evidence. Gateway observations identify gateway gaps and never define provider capabilities.

Unknown values stay unknown. Do not infer capabilities, limits, or prices from model names, another provider, a gateway response, or an SDK result.

## Credentials and sources

Set the provider credential named by `env_var` in `providers.yml` before refreshing or auditing a provider. A model refresh reports providers skipped for missing credentials, so read the command summary instead of assuming every requested catalog was written.

Use current vendor-owned API responses, schemas, or documentation as the primary source. A manually added model requires a source URL. Keep limits absent when the vendor does not publish them.

The gateway must already be running for behavioral audits:

```bash
export AIRLLM_GATEWAY_URL=http://127.0.0.1:8080
export AIRLLM_API_KEY=sk-inf-your-key
```

Do not store credentials in taxonomy files, model records, reports committed to Git, commands copied into documentation, or source URLs.

## Add a provider

Create a temporary provider definition:

```yaml
id: example
name: Example AI
homepage: https://example.ai
docs: https://docs.example.ai
base_url: https://api.example.ai/v1
models_url: https://api.example.ai/v1/models
openapi: https://api.example.ai/openapi.json
ingress: [oai]
auth: [bearer]
env_var: EXAMPLE_API_KEY
```

The currently supported completion surfaces are:

- `oai` for OpenAI Chat Completions
- `oai_responses` for OpenAI Responses
- `anthropic` for Anthropic Messages

Use one authentication entry when every surface shares it, or one entry per surface. Authentication values include `bearer` and `header_key:<header-name>`.

Set the credential and add the provider:

```bash
export EXAMPLE_API_KEY=...
uv run airllm-audit providers add /tmp/example-provider.yml
```

By default, this writes the provider definition, creates a placeholder icon when needed, extracts schemas, fetches models, enriches metadata, discovers request parameters, and regenerates the applied taxonomy. Use `--no-refresh` only when the provider cannot be fetched yet, then run `providers refresh example` later.

The generic catalog source handles an OpenAI-shaped model listing. If the provider paginates differently, returns another envelope, exposes richer metadata, or needs filtering, add one provider module under `../model-audit/catalog/scripts/sources/`. Subclass `ModelSource`, set its `id` and `url`, and map the provider response explicitly. Sources are discovered automatically, so there is no registry to edit. Do not invoke the individual catalog scripts directly.

Inspect the result:

```bash
uv run airllm-audit providers list
uv run airllm-audit models list --provider example
uv run airllm-audit taxonomy validate
```

To update an existing provider definition, pass the complete replacement document:

```bash
uv run airllm-audit providers add /tmp/example-provider.yml --replace
```

Use `--no-refresh` with `--replace` only when you intentionally want to update the declaration without fetching schemas and models in the same operation.

## Backfill or refresh every model for a provider

Set the provider credential, then run:

```bash
uv run airllm-audit models refresh anthropic
```

This fetches the provider's model listing, normalizes it, enriches limits and pricing where supported, discovers schema-backed parameter support, and rebuilds `taxonomy.yml`. Existing downstream metadata is carried forward for models still returned by the provider.

Use the broader provider refresh when schemas or provider API metadata may also have changed:

```bash
uv run airllm-audit providers refresh anthropic
```

Omit the provider to refresh every configured provider for which credentials are available:

```bash
uv run airllm-audit models refresh
uv run airllm-audit providers refresh
```

Always inspect additions, removals, changed upstream identifiers, limits, prices, and source stamps. A missing credential is a reported skip. An empty or unrecognized response is a failure and must not be treated as an empty catalog.

## Add or update one model

Prefer `models refresh <provider>` when the provider lists the model. Add a model manually only when an authoritative vendor source identifies it and the listing does not contain it:

```bash
uv run airllm-audit models add anthropic claude-example \
  --source https://docs.example.ai/models/claude-example \
  --context-window 200000 \
  --max-output-tokens 8192
```

Both token limits must be supplied together. Omit both when either value is unknown. A model without a known `context_length` remains in its provider catalog but is not emitted into the applied `taxonomy.yml`.

Update an existing model with `--replace`:

```bash
uv run airllm-audit models add anthropic claude-example \
  --source https://docs.example.ai/models/claude-example \
  --context-window 200000 \
  --max-output-tokens 16384 \
  --replace
```

Replacement preserves previously discovered metadata while applying the supplied source and limits. For provider-declared fields that the CLI does not expose, update the provider's source adapter and refresh the provider so the correction remains reproducible.

A manually added model that is still absent from an API-backed provider listing can be removed by a later refresh. Reapply the source-backed model after refreshing, or encode a durable, cited override in the provider-specific catalog source before relying on it.

Do not record live support or rejection results directly in `models/<provider>.json`. Use the behavioral audit workflow for capabilities, options, modalities, and feature combinations.

## Discover behavior and gateway gaps

Start with a bounded plan. The provider selector includes all cataloged models:

```bash
uv run airllm-audit runs plan --provider anthropic --case modalities
```

Run raw provider API comparisons against the provider's native gateway surface:

```bash
uv run airllm-audit runs execute \
  --provider anthropic \
  --case modalities \
  --concurrency 4
```

Use `--gateway-surface all` when auditing gateway parity across every ingress dialect:

```bash
uv run airllm-audit runs execute \
  --provider anthropic \
  --case modalities \
  --gateway-surface all \
  --concurrency 4
```

`--provider-surface` selects the direct upstream baseline. `--gateway-surface` selects the gateway ingress compared with that baseline. Without `--gateway-surface`, the gateway uses the provider's native surface.

Review the report before promoting evidence:

```bash
uv run airllm-audit reports show --gaps
uv run airllm-audit evidence accept model-audit/reports/<run>.json
```

Only raw HTTP API runs are eligible for taxonomy evidence. `--sdk` checks client compatibility and is intentionally rejected by `evidence accept`. Acceptance promotes usable direct observations, ignores gateway observations when deriving provider facts, writes `behavior.json`, and rebuilds `taxonomy.yml`.

A provider rejection can still be parity when the gateway rejects the same request for the same reason. Authentication, access, rate limits, timeouts, generic errors, and harness failures remain unknown rather than becoming unsupported capability claims.

## Generate and validate the taxonomy

Regenerate after any source catalog or accepted-evidence change:

```bash
uv run airllm-audit taxonomy build
```

Check whether generation would change `taxonomy.yml` without writing that file:

```bash
uv run airllm-audit taxonomy build --check
```

Run the complete validation before committing:

```bash
uv run airllm-audit cases coverage
uv run airllm-audit taxonomy validate
uv run pytest model-audit/tests -q
```

`taxonomy validate` checks provider and model structure, schema and icon references, case coverage, and whether `taxonomy.yml` is current. Generation and validation also refresh the deterministic `behavior.json` projection from accepted evidence, so inspect the working tree after either command.

## Review checklist

- Every manually asserted fact has a current authoritative source
- Unknown values remain null or absent
- Provider refresh output contains no unexpected skips or failures
- Model additions and removals are understood
- Prices and limits retain the correct provenance fields
- Behavioral claims came from accepted raw API evidence, never gateway or SDK output
- `behavior.json` and `taxonomy.yml` were generated, not hand-edited
- Case coverage and taxonomy validation pass
- The model-audit test suite passes
- No credentials or transient reports are included in the diff

See [`model-audit/README.md`](../model-audit/README.md) for the audit case format, surface matrix, parity semantics, and evidence lifecycle.
