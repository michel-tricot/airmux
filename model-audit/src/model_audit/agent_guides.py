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
4. Declare its typed `ProviderDefinition`; map provider model fields explicitly, including
   directional input modalities and output modalities, with at least one input and one output
   modality for every retained model
5. Add schema acquisition metadata for each supported surface when the provider publishes a usable specification
6. Set the credential named by the definition
7. Run `uv run airllm-audit providers onboard <provider>`
8. Review added models, exclusions, prices, schema coverage, provenance, and generated taxonomy
9. Run a bounded direct-provider audit before accepting behavioral evidence
10. Run the validation commands again and review the complete diff

The source module is the reproducible acquisition recipe. `providers.yml`, model catalogs,
schemas, and taxonomy are generated or maintained through the CLI. Never write a temporary
provider YAML definition.

Modalities describe directional content types such as text, image, audio, video, and PDF.
Capabilities describe behavior such as streaming, tools, reasoning, and structured output.
Never translate image support to a `vision` capability or PDF support to a `pdf` capability.
The shared catalog validator rejects modality spellings outside the canonical contract, and
taxonomy generation merges a new provider through the same evidence-aware projection without
provider-specific registration. A chat-shaped source may conservatively establish text input
and text output. Add documented or directly observed modalities to that baseline. Exclude a
model when neither provider-owned metadata nor a bounded direct probe can establish both
directions. Onboarding fails with every incomplete provider/model field named explicitly.
""",
        version=3,
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

The acquisition order is provider model API, current official provider documentation,
provider-scoped models.dev, cross-provider OpenRouter, provider-declared aliases, then
unknown. Official documentation extractors must preserve URLs, units, schedules, and tiers.

Use the provider-catalog skill again when an endpoint moved, a response shape changed,
documented facts conflict, a schema is not machine-readable, or a pricing extractor needs
judgment. Missing credentials, access failures, rate limits, empty payloads, and unrecognized
envelopes are acquisition failures and must not become provider facts.

Synchronization must leave every retained model with non-empty input and output modality
lists. Treat a newly incomplete model as an acquisition failure, inspect the named model,
then update the provider source with vendor-owned evidence or exclude it deliberately.
""",
        version=2,
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
`--input-modality` and `--output-modality` at least once, supply both token limits or neither,
and pass `--replace` for a correction.

Do not put live capability probes in the model catalog. Use a behavioral audit for
capabilities, options, modalities, interactions, and rejection semantics. After the change,
rebuild and validate taxonomy and confirm that a later provider sync will not silently remove
the manual record.
""",
        version=2,
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
4. Retry transient failures; exhausted transients are not evaluated and cannot become evidence
5. Keep access, generic, and harness failures unknown
6. Review the report before running `uv run airllm-audit evidence accept <report>`
7. Validate the generated taxonomy

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
independently valid. Direct raw HTTP requests must use provider-declared parameter aliases;
gateway requests keep the caller surface spelling.

Classify the result as translation, semantic, error-mapping, streaming, gateway rejection,
access, or harness behavior. A provider failure mirrored by the gateway is parity. Do not
change provider taxonomy to hide a gateway mismatch, and do not accept SDK evidence as
provider behavior.

Rate limits, timeouts, connection failures, and direct provider 5xx responses are transient.
Retry the affected side; if retries are exhausted, report parity as not evaluated rather than
inconclusive or mismatched.

Completed attempts that disagree are flaky, not inconclusive. Preserve every attempt and use
a strict majority for feature and parity; without a majority, leave parity not evaluated.
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

For a clean source audit, run `uv run airllm-audit taxonomy rebuild --preserve-as <name>`.
Compare every field with `uv run airllm-audit taxonomy diff <name> taxonomy`; use
`--summary` for counts and `--format json` for machine review.

Provider identity and declared metadata come from the catalog. Behavioral support comes only
from accepted direct API evidence. Unknown optional values stay unknown, stale case fingerprints
cannot contribute, and gateway or SDK observations never define provider support.

Input and output modalities are directional content types. Capabilities are behavioral features;
modality aliases such as `vision`, `pdf`, and `text` never enter the capability list. Catalog
metadata initializes modality support, then accepted direct evidence overrides the matching
direction and modality. Every retained catalog and applied model must have at least one input and
one output modality. Generation fails if direct evidence removes the last modality in either
direction. New providers use this projection automatically. A new modality spelling requires
adding it to the canonical contract and adding corresponding audit feature coverage before it can
be relied on for gateway admission.
""",
        version=3,
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
