# TokKeeper model audit

Model audit acquires provider catalogs, generates the applied taxonomy, and identifies
gateway gaps by comparing identical calls made directly and through a running TokKeeper data
plane.

The project has four independent verdicts:

- Execution reports whether the experiment completed, exhausted transient retries, was blocked by access, or failed in the harness
- Stability reports whether completed confirmation attempts agreed
- Feature reports whether the direct provider supports the exact claimed behavior profile
- Parity reports whether the gateway preserved the direct provider behavior

A matching provider rejection is parity. It is classified as unsupported only when the
provider explicitly rejects that feature or combination. Generic errors remain unknown.

Each claim in a case has its own assertion and feature verdict. A case that covers several
claims can therefore be `mixed` without hiding which capability or option passed. Parity is
evaluated independently from feature support.

## Architecture

Cases are semantic scenarios, not provider payloads. A discovered surface codec owns the
endpoint, request spelling, response normalization, streaming protocol, and continuation
state for one API dialect. Planning compiles both routes before a request is scheduled and
stores redacted rendered bodies plus semantic fingerprints in the report. A request that a
surface cannot represent is unavailable at planning time instead of failing during execution.

The execution output limit is separate from the request under test. `execution.max_output_tokens`
is a harness safety budget and does not claim model support. Only a case that sets
`request.max_tokens`, such as `parameters.max-tokens`, tests that option.

Observations retain normalized token counts, reasoning metadata, tool identities, typed
failure origin and retryability, and structured differences. Provider and gateway confirmation
attempts act as separate control arms, so a flaky result identifies provider, gateway, or
two-sided variance.

## Agent guides

The package owns versioned instructions for agents. List them with:

```bash
uv run tokkeeper-audit agent guides
uv run tokkeeper-audit agent guides --format json
```

Read one complete guide before an agent changes or interprets the catalog:

```bash
uv run tokkeeper-audit agent guide provider-onboarding
uv run tokkeeper-audit agent guide provider-sync
uv run tokkeeper-audit agent guide model-update
uv run tokkeeper-audit agent guide behavior-audit
uv run tokkeeper-audit agent guide gateway-investigation
uv run tokkeeper-audit agent guide taxonomy-generation
```

The repository `provider-catalog` skill is only the automatic-discovery adapter. These CLI
guides are the canonical instructions.

## Daily workflow

```bash
uv run tokkeeper-audit cases coverage
uv run tokkeeper-audit providers sources
uv run tokkeeper-audit providers list
uv run tokkeeper-audit models list --provider anthropic
uv run tokkeeper-audit runs plan --model anthropic/claude-fable-5
uv run tokkeeper-audit runs plan --provider anthropic --case modalities

export TOKKEEPER_GATEWAY_URL=http://127.0.0.1:8080
export TOKKEEPER_INFERENCE_KEY=sk-inf-your-key
uv run tokkeeper-audit runs execute --model anthropic/claude-fable-5
uv run tokkeeper-audit runs execute --provider anthropic --case modalities --concurrency 8

uv run tokkeeper-audit reports show --gaps
uv run tokkeeper-audit reports list
uv run tokkeeper-audit reports prune --keep 20 --yes
uv run tokkeeper-audit evidence accept model-audit/reports/<run>.json
uv run tokkeeper-audit taxonomy validate
```

The gateway must already be running. Model audit never starts or stops it. Raw HTTP
provider calls are the default and the only runs eligible for taxonomy evidence. `--sdk`
runs the same cases through the matching vendor SDK for client compatibility without
affecting provider facts.

`--case` accepts an exact case id or a namespace. Repeat it to combine selections.
`--provider` selects every cataloged model from one provider. Use `runs plan` before a
large execution to inspect its request count.

The provider and gateway surfaces are independent. By default, the direct call uses the
upstream egress configured for that model in the applied taxonomy. `--gateway-surface all`
then sends the same semantic request through Chat Completions, Responses, and Messages
ingress. This is the valid parity matrix because only the caller dialect changes.
Direct raw HTTP requests apply provider-declared parameter aliases from the catalog, while
gateway requests retain the selected caller surface spelling.

`--provider-surface` explicitly probes another direct provider surface. Use it for provider
capability discovery. Its parity result is diagnostic unless the applied model uses that
same upstream egress.

Runs execute up to four experiments concurrently by default. `--concurrency 1` provides
sequential execution for debugging. Each direct and gateway pair remains ordered, and
reports retain plan order regardless of completion order.

Rate limits, timeouts, connection failures, and direct provider 5xx responses are transient.
The runner retries only the affected side twice by default with exponential backoff. Configure
this with `--transient-retries` and `--retry-backoff`. If retries are exhausted, execution is
`transient failure` and parity is `not evaluated`; `inconclusive` is reserved for experiments
that cannot be compared because access or the harness prevents the test.

When completed confirmation attempts disagree, stability is `flaky`. A strict majority
determines feature and parity when one exists; otherwise feature remains `unknown` and parity
is `not evaluated`. Flaky results remain visible in reports but cannot become taxonomy evidence.

## Resume an interrupted run

`runs execute` creates its report before issuing the first request and checkpoints it after
every completed direct and gateway pair. If the process is interrupted, resume only the
missing experiments:

```bash
uv run tokkeeper-audit runs resume model-audit/reports/<run>.json
```

The checkpoint contains the complete original plan, confirmation count, transient retry policy,
request timeout, partial results, and completion state. Resume uses the stored gateway URL and
requires the gateway key through `TOKKEEPER_INFERENCE_KEY` or `--gateway-api-key`.

Resume rejects a changed taxonomy, case suite, audit source, or provider definition rather
than mixing evidence from different harness versions. It preserves original plan order and
may override concurrency, confirmations, transient retries, retry backoff, or request timeout
explicitly.

## Provider sources

Each provider has one auto-discovered source under
`model-audit/src/model_audit/catalog_tasks/sources/`. The source is the reproducible recipe for provider
identity, model acquisition, pricing supplied by the model endpoint, and schema acquisition.
`providers.yml` and the derived files are applied projections of that recipe.

Official documentation parsing lives under `model_audit/provider_docs/`, one module per
provider. Shared code only fetches documents, applies missing values, records exact source
URLs, and preserves conflicts. Provider-specific page structure never belongs in the shared
merger.

Inspect source readiness:

```bash
uv run tokkeeper-audit providers sources
```

A provider source declares a typed definition and maps its response explicitly:

```python
from model_audit.catalog_ops import ProviderDefinition, SchemaDefinition

from .base import ModelSource


class Example(ModelSource):
    id = "example"
    url = "https://api.example.ai/v1/models"
    definition = ProviderDefinition(
        id=id,
        name="Example AI",
        homepage="https://example.ai",
        docs="https://docs.example.ai",
        base_url="https://api.example.ai/v1",
        models_url=url,
        openapi="https://api.example.ai/openapi.json",
        ingress=("oai",),
        primary_surface="oai",
        auth=("bearer",),
        env_var="EXAMPLE_API_KEY",
    )
    schemas = (
        SchemaDefinition(
            surface="oai",
            url=definition.openapi,
            path_pattern=r"chat/completions$",
        ),
    )

    def normalize(self, item):
        return self.record(
            item["id"],
            context_length=item.get("context_length"),
            max_output_tokens=item.get("max_output_tokens"),
        )
```

OpenAI-shaped listing envelopes can inherit the generic item extraction, but every provider
still maps its fields explicitly. Add a custom `fetch` implementation for pagination or
multiple endpoints. Add a documentation-derived request schema only when no usable
machine-readable schema exists.

## Onboard a provider

The human or agent creates the provider source once. The user never writes provider YAML.
Set its credential and run:

```bash
export EXAMPLE_API_KEY=...
uv run tokkeeper-audit providers onboard example
```

Onboarding:

1. Loads the source through automatic discovery
2. Verifies its credential and model response before activating the provider
3. Promotes a matching candidate when present
4. Writes the typed provider definition and bootstrap seed
5. Pulls models, pricing, schemas, parameter metadata, and icons
6. Generates taxonomy and validates the catalog

An existing provider requires `--replace`. Missing definitions, credentials, empty model
responses, unrecognized envelopes, and source filter failures are reported as onboarding
errors rather than empty provider catalogs.

For an arbitrary provider, invoke the `provider-catalog` skill or read the
`provider-onboarding` guide. The CLI deliberately does not perform open-ended web research
or embed an LLM.

## Synchronize models, prices, and schemas

Synchronize every acquisition component for one provider:

```bash
uv run tokkeeper-audit providers sync anthropic
```

Synchronize every active provider with available credentials:

```bash
uv run tokkeeper-audit providers sync
```

Limit a run by repeating `--only`:

```bash
uv run tokkeeper-audit providers sync anthropic --only models
uv run tokkeeper-audit providers sync anthropic --only pricing
uv run tokkeeper-audit providers sync anthropic --only schemas --only parameters
uv run tokkeeper-audit providers sync anthropic --only icons
```

Model and pricing synchronization reacquire the provider model catalog before enrichment.
This keeps incremental synchronization equivalent to a clean rebuild and prevents stale
secondary prices and limits from surviving indefinitely.

The available components are `models`, `pricing`, `schemas`, `parameters`, and `icons`.
Model and schema synchronization also refreshes parameter discovery because that evidence
depends on both.

The provider API remains authoritative. Missing pricing and limits are filled in this order:

1. Provider model response
2. Current official provider documentation, with its exact URL
3. Provider-scoped `models.dev` catalog
4. Cross-provider OpenRouter catalog
5. Provider-declared aliases
6. Unknown

Provider values are never overwritten by secondary values. Context, maximum output, and
pricing provenance are independent. A secondary price is useful routing metadata, not a
billing guarantee.

A scoped sync preserves the previous successful model catalog when authentication fails,
the endpoint is unavailable, the response is empty, or its shape is unrecognized. The
command reports the failed component and exits nonzero.

## Clean rebuild and review

Preserve the current directory and reconstruct every generated artifact from provider
sources:

```bash
uv run tokkeeper-audit taxonomy rebuild --preserve-as taxonomy_old
uv run tokkeeper-audit taxonomy diff taxonomy_old taxonomy --summary
uv run tokkeeper-audit taxonomy diff taxonomy_old taxonomy --format json
```

The diff includes provider fields, every imported model field, applied taxonomy models,
schema hashes, and icon hashes. The rebuild fails rather than silently carrying an old
catalog through an acquisition error.

`taxonomy/reports/missing-metadata.json` is the explicit unknown-fact queue. It lists the
missing fields for each model without turning absence into an unsupported verdict.

## Add or correct one model

Prefer provider synchronization when the listing contains the model:

```bash
uv run tokkeeper-audit providers sync anthropic --only models
```

Add a source-backed model absent from the listing:

```bash
uv run tokkeeper-audit models add anthropic claude-example \
  --source https://docs.example.com/models/claude-example \
  --context-window 200000 \
  --max-output-tokens 8192
```

Both limits must be supplied together or omitted together. Correct an existing record with
`--replace`. A later provider sync may remove a manual model that remains absent from the
provider listing, so encode durable provider-specific behavior in its source module.

## Evidence and generated taxonomy

Live runs write JSON and HTML reports under `model-audit/reports/`. `evidence accept` is
the deliberate promotion boundary. It accepts usable direct observations from completed raw
HTTP runs, retains immutable observations, rejects SDK runs, and rebuilds generated taxonomy.

The deterministic reducer applies these rules:

- Confirmed direct success supports the exact claim profile
- Explicit provider rejection makes that exact profile unsupported
- Authentication and access failures remain unknown; exhausted transient failures are not promoted as evidence
- Flaky provider behavior is retained in reports but is not promoted as evidence
- Generic provider errors remain unknown
- Unknown evidence never overwrites conclusive evidence
- Conflicting equally recent conclusive evidence resolves to unknown
- Evidence stops affecting generated behavior when its case definition changes
- Profile-specific rejection never downgrades an entire capability or option family
- Gateway observations never change provider taxonomy

`taxonomy build` writes `taxonomy/behavior.json` and `taxonomy/taxonomy.yml`. Cases live
under `cases/` and declare exact claims, surface applicability, canonical requests, and
semantic oracles. `cases coverage` fails for missing feature coverage, missing endpoint
coverage, or unmapped canonical request fields.
