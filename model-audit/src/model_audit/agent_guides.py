from __future__ import annotations

from dataclasses import dataclass, replace
from importlib.resources import files


@dataclass(frozen=True)
class AgentGuide:
    id: str
    title: str
    use_when: str
    body: str
    version: int = 1
    references: tuple[str, ...] = ()


GUIDES = (
    AgentGuide(
        id="provider-onboarding",
        title="Onboard a provider",
        use_when="A provider has no active catalog entry or reproducible acquisition source",
        body="""# Provider onboarding

Use this guide when a provider is not active in the catalog. Research current facts from
vendor-owned APIs, OpenAPI documents, and documentation. Do not infer endpoints,
authentication, surfaces, limits, prices, or capabilities from another provider.

1. Run `uv run airllm-audit cases coverage` and `uv run airllm-audit taxonomy validate`
2. Locate the provider model listing, inference base URL, authentication method, supported
   surfaces, schemas, pricing, homepage, documentation, and icon
3. Add or update one auto-discovered provider source under `model-audit/catalog/scripts/sources/`
4. Declare its typed `ProviderDefinition`; map provider model fields explicitly and keep unknown values absent
5. Add schema acquisition metadata for each supported surface when the provider publishes a usable specification
6. Set the credential named by the definition
7. Run `uv run airllm-audit providers onboard <provider>`
8. Review added models, exclusions, prices, schema coverage, provenance, and generated taxonomy
9. Run a bounded direct-provider audit before accepting behavioral evidence
10. Run the validation commands again and review the complete diff

The source module is the reproducible acquisition recipe. `providers.yml`, model catalogs,
schemas, and taxonomy are generated or maintained through the CLI. Never write a temporary
provider YAML definition.
""",
        references=("sources", "fields", "provenance", "traps"),
    ),
    AgentGuide(
        id="provider-sync",
        title="Synchronize a provider",
        use_when="A known provider may have new models, prices, schemas, or parameter metadata",
        body="""# Provider synchronization

Use the deterministic CLI when the provider source still matches the upstream API.

1. Set the provider credential
2. Run `uv run airllm-audit providers sync <provider>`
3. Use repeated `--only` options to limit work to `models`, `pricing`, `schemas`, `parameters`, or `icons`
4. Review additions, removals, changed limits, price provenance, schema changes, skipped steps, and failures
5. Run `uv run airllm-audit taxonomy validate`

Model and pricing synchronization both reacquire the provider model catalog before applying
enrichment. This makes an incremental refresh converge with a clean rebuild and prevents
removed provider facts or stale secondary prices from being carried forward.

Use the provider-catalog skill again when an endpoint moved, a response shape changed,
documented facts conflict, a schema is not machine-readable, or a pricing extractor needs
judgment. Missing credentials, access failures, rate limits, empty payloads, and unrecognized
envelopes are acquisition failures and must not become provider facts.
""",
        references=("provenance", "traps"),
    ),
    AgentGuide(
        id="model-update",
        title="Add or correct one model",
        use_when="One model is missing or has incorrect source-backed metadata",
        body="""# Model update

Prefer `uv run airllm-audit providers sync <provider> --only models` when the provider lists
the model. If the model is absent from the listing, verify it against a current vendor-owned
source and run `uv run airllm-audit models add <provider> <model> --source <url>`. Supply both
token limits or neither, and pass `--replace` for a correction.

Do not put live capability probes in the model catalog. Use a behavioral audit for
capabilities, options, modalities, interactions, and rejection semantics. After the change,
rebuild and validate taxonomy and confirm that a later provider sync will not silently remove
the manual record.
""",
        references=("fields", "provenance"),
    ),
    AgentGuide(
        id="behavior-audit",
        title="Measure provider behavior",
        use_when="Capability, option, modality, interaction, or rejection behavior must be established",
        body="""# Behavior audit

1. Inspect the plan with `uv run airllm-audit runs plan`
2. Execute raw HTTP comparisons against an already running gateway with `uv run airllm-audit runs execute`
3. Treat matching success and matching explicit rejection as parity
4. Keep access failures, rate limits, timeouts, generic failures, and harness failures unknown
5. Review the report before running `uv run airllm-audit evidence accept <report>`
6. Validate the generated taxonomy

Only direct raw API observations can define provider behavior. SDK runs check client
compatibility, and gateway observations identify gaps; neither can become provider capability
evidence.
""",
        references=("provenance",),
    ),
    AgentGuide(
        id="gateway-investigation",
        title="Investigate a gateway gap",
        use_when="Direct provider and gateway behavior differ",
        body="""# Gateway investigation

Run the smallest reproducing model, case, provider surface, gateway surface, and transport.
Compare normalized status, semantic output, usage, reasoning, tool calls, error classification,
and streaming behavior. Confirm that direct authentication and gateway authentication are
independently valid.

Classify the result as translation, semantic, error-mapping, streaming, gateway rejection,
access, or harness behavior. A provider failure mirrored by the gateway is parity. Do not
change provider taxonomy to hide a gateway mismatch, and do not accept SDK evidence as
provider behavior.
""",
        references=("traps",),
    ),
    AgentGuide(
        id="taxonomy-generation",
        title="Generate taxonomy",
        use_when="Catalog metadata or accepted behavioral evidence changed",
        body="""# Taxonomy generation

Run `uv run airllm-audit taxonomy build`, then `uv run airllm-audit cases coverage` and
`uv run airllm-audit taxonomy validate`. Review `taxonomy/behavior.json` and
`taxonomy/taxonomy.yml` as generated projections; never edit them directly.

Provider identity and declared metadata come from the catalog. Behavioral support comes only
from accepted direct API evidence. Unknown values stay unknown, stale case fingerprints cannot
contribute, and gateway or SDK observations never define provider support.
""",
        references=("fields", "provenance"),
    ),
)


def guides() -> tuple[AgentGuide, ...]:
    return GUIDES


def guide(guide_id: str) -> AgentGuide:
    selected = next((item for item in GUIDES if item.id == guide_id), None)
    if selected is None:
        choices = ", ".join(item.id for item in GUIDES)
        message = f"unknown agent guide {guide_id}; choose from {choices}"
        raise ValueError(message)
    reference_root = files("model_audit").joinpath("guides")
    references = "\n\n".join(reference_root.joinpath(f"reference-{name}.md").read_text(encoding="utf-8").rstrip() for name in selected.references)
    body = f"{selected.body.rstrip()}\n\n{references}\n" if references else selected.body
    return replace(selected, body=body)
