# Taxonomy maintenance

This directory is generated provider catalog data consumed by TokKeeper. Maintain it from the
repository root through `tokkeeper-audit`. Do not invoke scripts under
`model-audit/catalog/scripts/` directly and do not edit `taxonomy.yml` or `behavior.json`.

## Choose the workflow

| Goal | Command or guide |
| --- | --- |
| Inspect provider source readiness | `uv run tokkeeper-audit providers sources` |
| Add a provider | `agent guide provider-onboarding`, then `providers onboard <provider>` |
| Refresh one provider | `uv run tokkeeper-audit providers sync <provider>` |
| Refresh all active providers | `uv run tokkeeper-audit providers sync` |
| Refresh models or prices | `providers sync <provider> --only models` or `--only pricing` |
| Refresh schemas or icons | `providers sync <provider> --only schemas` or `--only icons` |
| Add a sourced exception | `agent guide model-update`, then `models add` |
| Rebuild from nothing | `taxonomy rebuild --preserve-as taxonomy_old` |
| Compare two taxonomies | `taxonomy diff taxonomy_old taxonomy` |
| Measure behavior | `agent guide behavior-audit`, then `runs execute` |
| Investigate a gateway gap | `agent guide gateway-investigation` |
| Generate and validate | `taxonomy build`, then `taxonomy validate` |

Run these before and after maintenance:

```bash
uv run tokkeeper-audit cases coverage
uv run tokkeeper-audit taxonomy validate
```

## Skill, guide, and CLI

The repository `provider-catalog` skill recognizes catalog work and routes the agent to the
right workflow. The versioned agent guides embedded in `model-audit` contain research,
evidence, and review rules. The CLI performs deterministic acquisition and mutation.

List and read guides with:

```bash
uv run tokkeeper-audit agent guides
uv run tokkeeper-audit agent guide provider-onboarding
uv run tokkeeper-audit agent guide provider-sync
uv run tokkeeper-audit agent guide model-update
uv run tokkeeper-audit agent guide behavior-audit
uv run tokkeeper-audit agent guide gateway-investigation
uv run tokkeeper-audit agent guide taxonomy-generation
```

Use the CLI alone for a known repeatable operation such as refreshing an unchanged model
endpoint, rebuilding taxonomy, executing a defined audit matrix, or running validation.
Use an agent guide when source discovery, response mapping, schema interpretation, pricing
units, conflicting evidence, or failure classification requires judgment. Use both when
onboarding a provider or repairing an acquisition recipe.

## Source ownership

| Path | Ownership |
| --- | --- |
| `../model-audit/catalog/scripts/sources/` | Auto-discovered typed provider definitions and acquisition recipes |
| `providers.yml` | Applied provider endpoints, authentication, surfaces, and schema references |
| `models/<provider>.json` | Provider-listed text models, metadata, and provenance |
| `schemas/` | Provider request, response, and stream schemas |
| `../model-audit/definitions/features.yml` | Finite behavior vocabulary |
| `../model-audit/cases/` | Executable direct-provider versus gateway experiments |
| `../model-audit/evidence/accepted.json` | Deliberately accepted direct HTTP observations |
| `behavior.json` | Generated provider behavior projection |
| `taxonomy.yml` | Generated applied routing taxonomy |
| `../model-audit/reports/` | Checkpointed runs and gateway gap reports |

Provider declarations and observed behavior are distinct. Provider APIs, official specs,
and official documentation define catalog metadata. Direct raw HTTP observations define
behavior. Gateway observations identify gateway gaps and never define provider support.
Unknown means unknown, not unsupported.

## Add a provider

Read the onboarding guide. Research vendor-owned sources for the model listing, inference
base URL, authentication, supported surfaces, schemas, pricing, documentation, and icon.
Add one auto-discovered source module with a typed `ProviderDefinition` and explicit field
normalization. There is no provider registry and users do not write YAML definitions.

```bash
uv run tokkeeper-audit agent guide provider-onboarding
export EXAMPLE_API_KEY=...
uv run tokkeeper-audit providers onboard example
```

Use `--replace` when intentionally reapplying a changed definition to an active provider.
Onboarding verifies a nonempty recognized model response before activation, acquires every
component, builds taxonomy, and validates it.

## Refresh providers and models

```bash
uv run tokkeeper-audit providers sync anthropic
uv run tokkeeper-audit providers sync anthropic --only models
uv run tokkeeper-audit providers sync anthropic --only pricing
uv run tokkeeper-audit providers sync anthropic --only schemas --only parameters
uv run tokkeeper-audit providers sync anthropic --only icons
uv run tokkeeper-audit providers sync
```

Model and pricing refreshes reacquire the provider catalog before enrichment. An incremental
refresh therefore converges with a clean rebuild and cannot preserve stale facts as hidden
state. Missing credentials, authentication errors, rate limits, empty payloads, invalid
response shapes, and filters that keep no models are acquisition failures. They exit
nonzero and do not replace a previous successful catalog with an empty one.

For one API-listed model, refresh the provider. Use `models add` only for a current,
vendor-sourced model that the listing omits:

```bash
uv run tokkeeper-audit models add anthropic claude-example \
  --source https://docs.example.ai/models/claude-example \
  --input-modality text \
  --output-modality text \
  --context-window 200000 \
  --max-output-tokens 8192
```

Durable exceptions and filters belong in the provider source because a later refresh may
remove a manual record.

## Metadata and pricing provenance

Acquisition fills gaps in this order:

1. Provider model API
2. Current official provider documentation
3. Provider-scoped models.dev
4. Cross-provider OpenRouter
5. Provider-declared aliases
6. Unknown

Higher-ranked data is never overwritten. Official-document extractors must run on every
sync, record `documentation_url`, preserve pricing tiers and schedules, and distinguish
token, request, image, audio, and time units. Parser tests use representative frozen source
fragments. Context windows, maximum output limits, and prices keep independent provenance
because each can come from a different ranked source. Secondary prices are routing
estimates, not billing facts.

## Clean rebuild and difference audit

```bash
uv run tokkeeper-audit taxonomy rebuild --preserve-as taxonomy_old
uv run tokkeeper-audit taxonomy diff taxonomy_old taxonomy --summary
uv run tokkeeper-audit taxonomy diff taxonomy_old taxonomy --format json
```

The rebuild renames the complete existing directory and reconstructs providers, candidates,
routers, model catalogs, schemas, icons, reports, behavior, and applied taxonomy. It fails
on acquisition errors. The diff reports provider fields, every imported model field,
applied model fields, and schema and icon hashes. Use JSON for complete agent review and
the summary for a human overview.

`reports/missing-metadata.json` lists every unknown limit, capability flag, and price per
model. Modalities are required for every retained model, so a missing direction fails
acquisition or validation instead of entering this report. An entry is an investigation
queue, not evidence that the feature is unsupported.

When current provider-owned sources disagree, the higher-ranked source remains applied and
the model carries `source_conflicts` plus the conflicting `documentation_url` for review.

## Behavior and gateway parity

The gateway must already be running. Model audit never starts or stops it.

```bash
uv run tokkeeper-audit runs plan --provider anthropic --case modalities
uv run tokkeeper-audit runs execute \
  --provider anthropic \
  --case modalities \
  --gateway-surface all \
  --concurrency 100
```

Raw HTTP is the default and the only client mode eligible for provider evidence. Add
`--sdk` only to test vendor SDK compatibility. A matching direct and gateway success is
parity. A matching explicit rejection is also parity and records that the exact provider
feature profile is unsupported. Transient failures are retried and become `not evaluated`
if exhausted. Access and harness failures are inconclusive. Completed confirmation attempts
that disagree are flaky and cannot become taxonomy evidence. Generic errors remain unknown.

By default, the direct request uses the model's applied upstream egress while
`--gateway-surface all` varies only the caller dialect. Use `--provider-surface` for an
explicit provider capability probe; parity is diagnostic when that surface differs from
the model's applied egress.
Direct raw HTTP requests apply the provider's cataloged parameter aliases. Gateway requests
keep the selected caller surface spelling so the gateway remains responsible for translation.

Interrupted runs are checkpointed after every pair:

```bash
uv run tokkeeper-audit runs resume model-audit/reports/<run>.json --concurrency 100
```

Review before accepting evidence:

```bash
uv run tokkeeper-audit reports show model-audit/reports/<run>.json --gaps
uv run tokkeeper-audit evidence accept model-audit/reports/<run>.json
uv run tokkeeper-audit taxonomy validate
```

## Review checklist

- Every asserted fact has current provenance
- Official documentation records its exact URL and correct unit
- Unknown optional values remain absent; every model has non-empty input and output modalities
- Provider acquisition has no unexplained skip or failure
- Additions, removals, aliases, limits, prices, and retirements are understood
- Behavioral claims came only from accepted direct raw HTTP evidence
- Gateway and SDK observations did not become provider capabilities
- Generated files are current
- No credential or transient secret appears in the diff

See [`model-audit/README.md`](../model-audit/README.md) for experiment semantics, surfaces,
checkpointing, and the evidence lifecycle.
