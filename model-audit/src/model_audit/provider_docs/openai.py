from __future__ import annotations

import re

from model_audit.provider_docs.base import ModelDocumentation, markdown_modalities, markdown_price, token_count


def parse_openai_model(markdown: str, source: str) -> ModelDocumentation:
    model_match = re.search(r"^Model ID:\s*`([^`]+)`", markdown, flags=re.MULTILINE)
    if model_match is None:
        message = f"OpenAI model page has no model id: {source}"
        raise ValueError(message)
    snapshot_section = markdown.split("## Snapshots", 1)[1].split("\n## ", 1)[0] if "## Snapshots" in markdown else ""
    snapshots = re.findall(r"^-\s*`([^`]+)`", snapshot_section, flags=re.MULTILINE)
    default = re.search(r"^-\s*Default snapshot:\s*`([^`]+)`", markdown, flags=re.MULTILINE)
    ids = tuple(dict.fromkeys((model_match.group(1), *((default.group(1),) if default else ()), *snapshots)))
    context = re.search(r"^-\s*([\d,.]+\s*[KMB]?)\s+context window", markdown, flags=re.MULTILINE | re.IGNORECASE)
    output = re.search(r"^-\s*([\d,.]+\s*[KMB]?)\s+max output tokens", markdown, flags=re.MULTILINE | re.IGNORECASE)
    features_section = markdown.split("## Supported features", 1)[1].split("\n## ", 1)[0] if "## Supported features" in markdown else ""
    features = set(re.findall(r"^-\s*([a-z0-9_]+)\s*$", features_section, flags=re.MULTILINE))
    prices = {
        "input_per_mtok": markdown_price(markdown, "Input"),
        "cached_input_per_mtok": markdown_price(markdown, "Cached input"),
        "output_per_mtok": markdown_price(markdown, "Output"),
    }
    pricing = {name: value for name, value in prices.items() if value is not None}
    values: dict[str, object] = {
        "context_length": token_count(context.group(1)) if context else None,
        "max_output_tokens": token_count(output.group(1)) if output else None,
        "input_modalities": markdown_modalities(markdown, "Input"),
        "output_modalities": markdown_modalities(markdown, "Output"),
        "supports_tools": "function_calling" in features,
        "supports_structured_output": "structured_outputs" in features,
        "supports_thinking": "Reasoning token support" in markdown,
        "pricing": pricing or None,
    }
    return ModelDocumentation(ids=ids, source=source, values={name: value for name, value in values.items() if value is not None})


def parse_openai_pricing(markdown: str, source: str) -> tuple[ModelDocumentation, ...]:
    pattern = re.compile(
        r"\|\s*[^|]+\|\s*`?([a-zA-Z0-9][a-zA-Z0-9._/-]*)`?\s*\|\s*\$([\d.]+)\s*\|\s*(?:\$([\d.]+)|-)\s*\|\s*(?:\$([\d.]+)|-)\s*\|",
        flags=re.IGNORECASE,
    )
    return tuple(
        ModelDocumentation(
            ids=(model_id,),
            source=source,
            values={
                "pricing": {
                    "input_per_mtok": float(input_price),
                    **({"cached_input_per_mtok": float(cached_price)} if cached_price else {}),
                    **({"output_per_mtok": float(output_price)} if output_price else {}),
                }
            },
        )
        for model_id, input_price, cached_price, output_price in pattern.findall(markdown)
    )
