---
name: provider-catalog
description: Research and maintain the LLM provider catalog and model audit under taxonomy/ and model-audit/: adding a provider or model, refreshing provider-derived models, extracting schemas, collecting direct API evidence, generating taxonomy, or answering what a provider accepts.
user-invocable: true
---

# Provider catalog and model audit

Use the root `airllm-audit` CLI and [model-audit/README.md](../../../model-audit/README.md) for every catalog and behavior workflow. The scripts retained beside this skill are legacy implementation history and must not be run.

## Sources of truth

- `taxonomy/providers.yml`, `taxonomy/routers.yml`, schemas, icons, and model catalogs contain provider identity, declared metadata, and schema-derived facts
- `model-audit/definitions/features.yml` defines the finite capability, option, modality, interaction, and behavior vocabulary
- `model-audit/cases/` defines executable direct-versus-gateway experiments with exact claims and semantic oracles
- `model-audit/evidence/accepted.json` contains deliberately promoted direct API observations
- `taxonomy/behavior.json` and `taxonomy/taxonomy.yml` are generated outputs

Never store live behavior, reachability, or parameter probes in `taxonomy/models/*.json`. Never infer provider behavior from gateway observations or SDK runs.

## Research rules

Provider APIs, model lists, authentication, limits, and prices are unstable. Verify current facts against vendor-owned API responses, OpenAPI schemas, or documentation before changing the catalog. Unknown facts remain absent or null. Keep authoritative source URLs with manually added models.

## Workflows

Before and after changes, run:

```bash
uv run airllm-audit cases coverage
uv run airllm-audit taxonomy validate
```

Add and derive a provider from a validated YAML definition:

```bash
uv run airllm-audit providers add provider.yml
```

OpenAI-shaped model listing endpoints use the generic source. Add a module under `model-audit/catalog/scripts/sources/` only when the provider response needs explicit hand mapping. Sources are discovered automatically.

Refresh every model for one provider:

```bash
uv run airllm-audit models refresh <provider>
```

Add one model that is missing from the listing:

```bash
uv run airllm-audit models add <provider> <model> --source <vendor-url> --context-window <tokens> --max-output-tokens <tokens>
```

Existing providers and models require explicit `--replace`.

Discover model behavior and gateway gaps through an already running data plane:

```bash
uv run airllm-audit runs plan --provider <provider>
uv run airllm-audit runs execute --provider <provider> --gateway-url http://127.0.0.1:8080
uv run airllm-audit reports show --gaps
uv run airllm-audit evidence accept model-audit/reports/<run>.json
```

Raw API is the default and the only evidence source. `--sdk` checks vendor SDK compatibility but cannot affect taxonomy. Evidence acceptance rebuilds generated behavior and routing taxonomy.

## Invariants

- Matching direct and gateway success is parity
- Matching explicit rejection is parity and exact-profile unsupported behavior
- Matching generic failure is parity with unknown feature support
- Profile-specific rejection never downgrades an entire capability or option family
- Gateway-only differences are gateway gaps
- Access and harness failures are reported independently from feature and parity
- Stale case fingerprints cannot affect generated behavior
- The planner never skips a case based on current taxonomy support
- `cases coverage` must report zero missing claims, endpoint gaps, and unmapped canonical request fields
- Generated catalog and evidence output must remain deterministic and reviewable
