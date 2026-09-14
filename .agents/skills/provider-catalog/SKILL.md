---
name: provider-catalog
description: Research and maintain the LLM provider catalog and model audit under taxonomy/ and model-audit/: onboarding or synchronizing providers, updating models or pricing, collecting direct API evidence, generating taxonomy, or investigating gateway gaps.
user-invocable: true
---

# Provider catalog entrypoint

The `model-audit` package owns the canonical, versioned agent instructions. Before taking
task actions, select the matching guide and read its complete text:

| Task | Guide |
| --- | --- |
| Add a provider and derive models, prices, schemas, and taxonomy | `provider-onboarding` |
| Refresh models, pricing, schemas, parameters, or icons | `provider-sync` |
| Add or correct one model | `model-update` |
| Establish provider feature behavior | `behavior-audit` |
| Diagnose a direct-provider versus gateway difference | `gateway-investigation` |
| Rebuild or validate generated taxonomy | `taxonomy-generation` |

Run:

```bash
uv run tokkeeper-audit agent guide <guide> --format text
```

Follow the returned guide as the authority for the workflow. Use the root `tokkeeper-audit`
CLI for every catalog mutation, live experiment, evidence promotion, generation, and
validation. Do not run the internal task modules under `model-audit/src/model_audit/catalog_tasks/`.

Every retained model must have non-empty canonical input and output modality lists. When a
provider omits them, establish a conservative chat baseline from its surface, enrich it from
provider-owned documentation or direct evidence, or exclude the model. Never allow onboarding,
synchronization, manual model addition, or taxonomy generation to preserve an empty direction.
