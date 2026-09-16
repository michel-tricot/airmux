from __future__ import annotations

from decimal import Decimal
from typing import cast

from model_audit.provider_docs import (
    ModelDocumentation,
    apply_documentation,
    parse_anthropic_model,
    parse_deepseek_pricing,
    parse_fireworks_model,
    parse_fireworks_pricing,
    parse_mistral_index,
    parse_mistral_model,
    parse_openai_model,
    parse_openai_pricing,
    parse_together_models,
)


def mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return cast("dict[str, object]", value)


def test_openai_model_markdown_maps_snapshots_to_provider_metadata():
    metadata = parse_openai_model(
        """
Model ID: `gpt-example`

## Model details
- Default snapshot: `gpt-example-2026-01-01`
- Input modalities: text, image
- Output modalities: text
- 1,050,000 context window
- 128,000 max output tokens

### Text tokens
| Input | $2.5 | 1M tokens |
| Cached input | $0.25 | 1M tokens |
| Output | $15 | 1M tokens |

## Supported features
- streaming
- structured_outputs
- function_calling

## Snapshots
- `gpt-example-2026-01-01`
""",
        "https://provider.example/gpt-example.md",
    )

    assert metadata.ids == ("gpt-example", "gpt-example-2026-01-01")
    assert metadata.values["context_length"] == 1_050_000
    assert metadata.values["max_output_tokens"] == 128_000
    assert metadata.values["pricing"] == {
        "input_per_mtok": Decimal("2.5"),
        "cached_input_per_mtok": Decimal("0.25"),
        "output_per_mtok": Decimal(15),
    }
    assert metadata.values["supports_tools"] is True
    assert metadata.values["supports_structured_output"] is True


def test_openai_pricing_page_fills_models_absent_from_model_index():
    documents = parse_openai_pricing(
        """
| Category | Model | Input | Cached input | Output |
| --- | --- | --- | --- | --- |
| Search | `gpt-search-api` | $1.25 | $0.125 | $10.00 |
""",
        "https://provider.example/pricing.md",
    )

    assert documents[0].ids == ("gpt-search-api",)
    assert documents[0].values["pricing"] == {
        "input_per_mtok": Decimal("1.25"),
        "cached_input_per_mtok": Decimal("0.125"),
        "output_per_mtok": Decimal("10.00"),
    }


def test_anthropic_model_markdown_reads_cache_prices():
    metadata = parse_anthropic_model(
        """
Model ID: `claude-example`
Context window: 1M tokens · Max output: 128K tokens · Input pricing: $3 / MTok · Output pricing: $15 / MTok

| Input | $3 / MTok |
| Output | $15 / MTok |
| [5m cache write](https://provider.example/cache) | $3.75 / MTok |
| [1h cache write](https://provider.example/cache) | $6 / MTok |
| [Cache read](https://provider.example/cache) | $0.30 / MTok |
""",
        "https://provider.example/claude-example.md",
    )

    assert metadata.values["context_length"] == 1_000_000
    assert metadata.values["max_output_tokens"] == 128_000
    pricing = mapping(metadata.values["pricing"])
    assert pricing["cache_write_per_mtok"] == Decimal("3.75")
    tiers = mapping(pricing["tiers"])
    one_hour = mapping(tiers["one_hour_cache_write"])
    assert one_hour["cache_write_per_mtok"] == Decimal(6)


def test_fireworks_pricing_uses_standard_as_default_and_keeps_priority():
    prices = parse_fireworks_pricing(
        """
| [Example](https://app.fireworks.ai/models/fireworks/example-model) | \\$0.22 / \\$0.007 / \\$0.66 | \\$0.275 / \\$0.00875 / \\$0.825 |
| [Example Fast](https://app.fireworks.ai/models/fireworks/example-model) | \\$0.44 / \\$0.014 / \\$1.32 | — |
""",
        "https://provider.example/pricing.md",
    )

    pricing = mapping(prices["example-model"].values["pricing"])
    assert pricing["input_per_mtok"] == Decimal("0.22")
    assert pricing["cached_input_per_mtok"] == Decimal("0.007")
    tiers = mapping(pricing["tiers"])
    priority = mapping(tiers["priority"])
    assert priority["output_per_mtok"] == Decimal("0.825")


def test_fireworks_model_page_records_serverless_source_conflict():
    metadata = parse_fireworks_model(
        """
<span>accounts/fireworks/models/example-model</span>
<span>Serverless</span><span>Not supported</span>
""",
        "https://app.fireworks.ai/models/fireworks/example-model",
    )

    assert metadata.ids == ("example-model",)
    assert metadata.values["source_conflicts"] == [
        "provider API reports supportsServerless=true; official model page reports Serverless: Not supported"
    ]


def test_deepseek_pricing_keeps_peak_and_off_peak_rates():
    metadata = parse_deepseek_pricing(
        """
<tr><td colspan="3">MODEL</td><td>deepseek-flash</td><td>deepseek-pro</td></tr>
<tr><td colspan="3">CONTEXT LENGTH</td><td colspan="2">1M</td></tr>
<tr><td colspan="3">MAX OUTPUT</td><td colspan="2">MAXIMUM: 384K</td></tr>
<tr><td rowspan="2">CACHE HIT</td><td>OFF-PEAK</td><td>$0.007</td><td>$0.022</td></tr>
<tr><td>PEAK</td><td>$0.014</td><td>$0.044</td></tr>
<tr><td rowspan="2">CACHE MISS</td><td>OFF-PEAK</td><td>$0.22</td><td>$0.66</td></tr>
<tr><td>PEAK</td><td>$0.44</td><td>$1.32</td></tr>
<tr><td rowspan="2">OUTPUT</td><td>OFF-PEAK</td><td>$0.66</td><td>$1.98</td></tr>
<tr><td>PEAK</td><td>$1.32</td><td>$3.96</td></tr>
""",
        "https://provider.example/pricing",
    )

    flash = metadata["deepseek-flash"].values
    pricing = mapping(flash["pricing"])
    assert pricing["input_per_mtok"] == Decimal("0.44")
    tiers = mapping(pricing["tiers"])
    off_peak = mapping(tiers["off_peak"])
    assert off_peak["input_per_mtok"] == Decimal("0.22")
    assert off_peak["output_per_mtok"] == Decimal("0.66")


def test_mistral_index_and_model_page_map_aliases_to_official_pricing():
    urls = parse_mistral_index(
        '<a href="/models/mistral-example-26-01">Example</a>',
        "https://docs.mistral.ai/models",
    )
    assert urls == ("https://docs.mistral.ai/models/mistral-example-26-01",)

    metadata = parse_mistral_model(
        """
<button title="Click to copy: mistral-example-2601">mistral-example-2601</button>
<button title="Click to copy: mistral-example-latest">mistral-example-latest</button>
<span>Context</span><div class="text-lg">256k</div>
<span>Price</span><span>$<!-- -->0.5</span><span>$<!-- -->1.5</span>
""",
        urls[0],
    )
    assert metadata.ids == ("mistral-example-2601", "mistral-example-latest")
    assert metadata.values["context_length"] == 256_000
    assert metadata.values["pricing"] == {"input_per_mtok": Decimal("0.5"), "output_per_mtok": Decimal("1.5")}


def test_mistral_model_page_reads_serialized_pricing_data():
    metadata = parse_mistral_model(
        r"""
<button title="Click to copy: mistral-example-2601">mistral-example-2601</button>
<span>Context</span><div class="text-lg">256k</div>
\"pricing\":{\"type\":\"custom\",\"input\":[
{\"type\":\"range\",\"price\":0.004,\"denominator\":\"/Min\"},
{\"type\":\"range\",\"price\":0.5,\"denominator\":\"/M Tokens\"},
{\"type\":\"range\",\"price\":0.05,\"denominator\":\"/M Tokens\"}],
\"output\":[{\"type\":\"range\",\"price\":1.5,\"denominator\":\"/M Tokens\"}]}
""",
        "https://docs.mistral.ai/models/mistral-example-26-01",
    )

    assert metadata.values["pricing"] == {
        "input_per_mtok": Decimal("0.5"),
        "cached_input_per_mtok": Decimal("0.05"),
        "output_per_mtok": Decimal("1.5"),
    }


def test_official_documentation_applies_through_provider_declared_aliases():
    models: list[dict[str, object]] = [
        {"id": "model-latest", "aliases": ["model-2026"], "context_length": 10, "context_source": "provider", "pricing": None}
    ]
    documents = (
        ModelDocumentation(
            ids=("model-2026",),
            source="https://provider.example/models/model-2026",
            values={"context_length": 20, "pricing": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}},
        ),
    )

    enriched = apply_documentation(models, documents)

    assert enriched[0]["context_length"] == 10
    assert enriched[0]["context_source"] == "provider"
    assert enriched[0]["pricing_source"] == "vendor-docs"
    assert enriched[0]["documentation_url"] == "https://provider.example/models/model-2026"


def test_together_serverless_table_maps_declared_features_and_prices():
    documents = parse_together_models(
        r"""
## Chat models
| Qwen | Example | Qwen/Example | 262144 | \$1.25 | \$0.25 | \$3.75 | FP8 | Yes | No |
""",
        "https://provider.example/serverless-models",
    )

    assert documents[0].ids == ("Qwen/Example",)
    assert documents[0].values["context_length"] == 262144
    assert documents[0].values["supports_tools"] is True
    assert documents[0].values["supports_structured_output"] is False
    assert documents[0].values["input_modalities"] == ["text"]
    assert documents[0].values["output_modalities"] == ["text"]
    assert documents[0].values["pricing"] == {
        "input_per_mtok": Decimal("1.25"),
        "cached_input_per_mtok": Decimal("0.25"),
        "output_per_mtok": Decimal("3.75"),
    }


def test_together_vision_table_augments_the_chat_model_modalities():
    documents = parse_together_models(
        r"""
## Chat models
| Qwen | Example | Qwen/Example | 262144 | \$1.25 | \$0.25 | \$3.75 | FP8 | Yes | No |
## Vision models
| Qwen | Example | Qwen/Example | 262144 | \$1.25 | \$3.75 |
""",
        "https://provider.example/serverless-models",
    )

    assert len(documents) == 1
    assert documents[0].values["input_modalities"] == ["text", "image"]
    assert documents[0].values["output_modalities"] == ["text"]
