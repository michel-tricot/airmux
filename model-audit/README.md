# AirLLM model audit

Model audit discovers provider behavior, generates the applied model taxonomy, and identifies gateway gaps by comparing identical calls made directly and through a running AirLLM data plane.

The project has three independent verdicts:

- Execution reports whether the experiment completed, was blocked by access, or failed in the harness
- Feature reports whether the direct provider supports the exact claimed behavior profile
- Parity reports whether the gateway preserved the direct provider behavior

A matching provider rejection is parity. It is classified as unsupported only when the provider explicitly rejects that feature or combination. Generic errors remain unknown.

## Daily workflow

```bash
uv run airllm-audit cases coverage
uv run airllm-audit models list --provider anthropic
uv run airllm-audit runs plan --model anthropic/claude-fable-5

export AIRLLM_GATEWAY_URL=http://127.0.0.1:8080
export AIRLLM_API_KEY=sk-inf-your-key
uv run airllm-audit runs execute --model anthropic/claude-fable-5

uv run airllm-audit reports show --gaps
uv run airllm-audit evidence accept model-audit/reports/<run>.json
uv run airllm-audit taxonomy validate
```

The gateway must already be running. Model audit never starts or stops it. Raw HTTP provider calls are the default and the only runs eligible for taxonomy evidence. `--sdk` runs the same cases through the matching vendor SDK for client compatibility without affecting provider facts.

## Add one model

Refresh a provider to derive every model from its listing API:

```bash
uv run airllm-audit models refresh anthropic
```

Add one model from an authoritative vendor source when it is not listed:

```bash
uv run airllm-audit models add anthropic claude-example \
  --source https://docs.example.com/models/claude-example \
  --context-window 200000 \
  --max-output-tokens 8192
```

The source is required and retained on the model record. Unknown limits stay unknown rather than inheriting a default. Adding an existing model fails unless `--replace` is explicit; replacement preserves metadata discovered from the provider catalog.

## Add one provider

Create a provider definition:

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

Then add and derive it:

```bash
export EXAMPLE_API_KEY=...
uv run airllm-audit providers add example.yml
uv run airllm-audit runs execute --provider example --gateway-url http://127.0.0.1:8080
```

OpenAI-shaped model listing responses work without provider-specific code. Add a focused module under `model-audit/catalog/scripts/sources/` only when the provider publishes richer or different metadata. Sources are discovered automatically.

Adding an existing provider fails unless `--replace` is explicit.

## Evidence and generated taxonomy

Live runs write transient JSON and HTML reports under `model-audit/reports/`. `evidence accept` is the deliberate promotion boundary. It accepts usable direct observations from raw HTTP runs, retains immutable observations, rejects SDK runs, and rebuilds the generated taxonomy. A gateway-side failure does not discard a valid direct provider observation.

The deterministic reducer applies these rules:

- Confirmed direct success supports the exact claim profile
- Explicit provider rejection makes that exact profile unsupported
- Authentication, access, rate limits, timeouts, and generic errors remain unknown
- Unknown evidence never overwrites conclusive evidence
- Conflicting equally recent conclusive evidence resolves to unknown
- Evidence stops affecting generated behavior when its case definition changes
- Profile-specific rejection never downgrades an entire capability or option family
- Gateway observations never change provider taxonomy

`taxonomy build` writes:

- `taxonomy/behavior.json`, the complete behavioral evidence projection
- `taxonomy/taxonomy.yml`, the routing projection consumed by the control plane

## Extend coverage

Features live in `definitions/features.yml`. Cases live under `cases/` and declare exact claims, surface applicability, canonical requests, and semantic oracles. Add one case for one behavior. Add interaction cases only when the combination itself is the subject.

`cases coverage` fails when any required feature lacks a case, when a declared endpoint has no applicable case, or when a canonical request field has no feature mapping. The planner never consults existing support metadata, so stale taxonomy cannot prevent discovery.
