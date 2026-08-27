from __future__ import annotations

import html
import math
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import cast

import httpx

USER_AGENT = {"User-Agent": "airllm-taxonomy/1.0", "Accept": "text/markdown,text/plain,text/html"}
PRICE_FIELD_COUNT = 3
PAIR_FIELD_COUNT = 2
TOGETHER_FIELD_COUNT = 10


@dataclass(frozen=True)
class ModelDocumentation:
    ids: tuple[str, ...]
    source: str
    values: dict[str, object]


def fetch_text(url: str) -> str:
    response = httpx.get(url, headers=USER_AGENT, timeout=90, follow_redirects=True)
    response.raise_for_status()
    return response.text


def fetch_texts(urls: tuple[str, ...]) -> dict[str, str]:
    with ThreadPoolExecutor(max_workers=min(12, len(urls) or 1), thread_name_prefix="provider-docs") as executor:
        return dict(zip(urls, executor.map(fetch_text, urls), strict=True))


def _token_count(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*([\d,.]+)\s*([KMB]?)\s*(?:tokens?)?\s*", value, flags=re.IGNORECASE)
    if match is None:
        return None
    scale = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[match.group(2).upper()]
    return int(float(match.group(1).replace(",", "")) * scale)


def _price(markdown: str, label: str) -> float | None:
    match = re.search(
        rf"\|\s*(?:\[)?{re.escape(label)}(?:\]\([^)]+\))?\s*\|\s*\\?\$([\d.]+)",
        markdown,
        flags=re.IGNORECASE,
    )
    return float(match.group(1)) if match is not None else None


def _modalities(markdown: str, label: str) -> list[str] | None:
    match = re.search(rf"^-\s*{re.escape(label)} modalities:\s*(.+)$", markdown, flags=re.MULTILINE | re.IGNORECASE)
    return [value.strip() for value in match.group(1).split(",")] if match is not None else None


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
        "input_per_mtok": _price(markdown, "Input"),
        "cached_input_per_mtok": _price(markdown, "Cached input"),
        "output_per_mtok": _price(markdown, "Output"),
    }
    pricing = {name: value for name, value in prices.items() if value is not None}
    values: dict[str, object] = {
        "context_length": _token_count(context.group(1)) if context else None,
        "max_output_tokens": _token_count(output.group(1)) if output else None,
        "input_modalities": _modalities(markdown, "Input"),
        "output_modalities": _modalities(markdown, "Output"),
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


def parse_anthropic_model(markdown: str, source: str) -> ModelDocumentation:
    model_match = re.search(r"^Model ID:\s*`([^`]+)`", markdown, flags=re.MULTILINE)
    if model_match is None:
        message = f"Anthropic model page has no model id: {source}"
        raise ValueError(message)
    context = re.search(r"Context window:\s*([\d,.]+\s*[KMB]?)\s*tokens", markdown, flags=re.IGNORECASE)
    output = re.search(r"Max output:\s*([\d,.]+\s*[KMB]?)\s*tokens", markdown, flags=re.IGNORECASE)
    prices = {
        "input_per_mtok": _price(markdown, "Input"),
        "output_per_mtok": _price(markdown, "Output"),
        "cached_input_per_mtok": _price(markdown, "Cache read"),
        "cache_write_per_mtok": _price(markdown, "5m cache write"),
    }
    pricing: dict[str, object] = {name: value for name, value in prices.items() if value is not None}
    one_hour = _price(markdown, "1h cache write")
    if one_hour is not None:
        pricing["tiers"] = {"one_hour_cache_write": {"cache_write_per_mtok": one_hour}}
    values: dict[str, object] = {
        "context_length": _token_count(context.group(1)) if context else None,
        "max_output_tokens": _token_count(output.group(1)) if output else None,
        "pricing": pricing or None,
    }
    return ModelDocumentation(ids=(model_match.group(1),), source=source, values={name: value for name, value in values.items() if value is not None})


def _price_triplet(value: str) -> dict[str, float] | None:
    amounts = [float(amount) for amount in re.findall(r"\\?\$([\d.]+)", value)]
    if len(amounts) != PRICE_FIELD_COUNT:
        return None
    return {"input_per_mtok": amounts[0], "cached_input_per_mtok": amounts[1], "output_per_mtok": amounts[2]}


def parse_fireworks_pricing(markdown: str, source: str) -> dict[str, ModelDocumentation]:
    pattern = re.compile(
        r"\[[^\]]+\]\(https://app\.fireworks\.ai/models/fireworks/([^)]+)\)\s*\|\s*([^|]+)\|\s*([^|]+)\|",
        flags=re.IGNORECASE,
    )
    prices: dict[str, ModelDocumentation] = {}
    for model_id, standard_value, priority_value in pattern.findall(markdown):
        if model_id in prices or (standard := _price_triplet(standard_value)) is None:
            continue
        priority = _price_triplet(priority_value)
        pricing: dict[str, object] = dict(standard)
        if priority is not None:
            pricing["tiers"] = {"priority": priority}
        prices[model_id] = ModelDocumentation(ids=(model_id,), source=source, values={"pricing": pricing})
    return prices


def parse_fireworks_model(document: str, source: str) -> ModelDocumentation:
    model_id = urllib.parse.urlparse(source).path.rstrip("/").rsplit("/", 1)[-1]
    if not model_id:
        message = f"Fireworks model page has no model id: {source}"
        raise ValueError(message)
    serverless = re.search(r">Serverless</span>.*?<span[^>]*>([^<]+)</span>", document, flags=re.DOTALL | re.IGNORECASE)
    values: dict[str, object] = {}
    if serverless is not None and serverless.group(1).strip().lower() == "not supported":
        values["source_conflicts"] = ["provider API reports supportsServerless=true; official model page reports Serverless: Not supported"]
    return ModelDocumentation(ids=(model_id,), source=source, values=values)


def parse_mistral_index(document: str, source: str) -> tuple[str, ...]:
    paths = re.findall(r'href="(/models/[^"?#]+)"', document, flags=re.IGNORECASE)
    return tuple(dict.fromkeys(urllib.parse.urljoin(source, path) for path in paths))


def parse_mistral_model(document: str, source: str) -> ModelDocumentation:
    ids = tuple(dict.fromkeys(re.findall(r'title="Click to copy: ([^"]+)"', document)))
    if not ids:
        message = f"Mistral model page has no API model id: {source}"
        raise ValueError(message)
    context = re.search(r">Context</span>.*?<div[^>]*text-lg[^>]*>([\d,.]+\s*[KMB]?)</div>", document, flags=re.DOTALL | re.IGNORECASE)
    serialized = html.unescape(document).replace(r'\"', '"')
    pricing_match = re.search(
        r'"pricing":\{"type":"custom".*?"input":\[(.*?)\],\s*"output":\[(.*?)\]\}',
        serialized,
        flags=re.DOTALL,
    )
    pricing: dict[str, float] = {}
    if pricing_match is not None:
        input_prices = [
            float(price.group(1))
            for item in re.findall(r"\{[^{}]*\}", pricing_match.group(1))
            if '"denominator":"/M Tokens"' in item and (price := re.search(r'"price":([\d.]+)', item)) is not None
        ]
        output_prices = [
            float(price.group(1))
            for item in re.findall(r"\{[^{}]*\}", pricing_match.group(2))
            if '"denominator":"/M Tokens"' in item and (price := re.search(r'"price":([\d.]+)', item)) is not None
        ]
        if input_prices:
            pricing["input_per_mtok"] = input_prices[0]
        if len(input_prices) > 1:
            pricing["cached_input_per_mtok"] = input_prices[1]
        if output_prices:
            pricing["output_per_mtok"] = output_prices[0]
    elif ">Price</span>" in document:
        pricing_section = document.split(">Price</span>", 1)[1]
        prices = [float(value) for value in re.findall(r"\$(?:<!--\s*-->)?([\d.]+)", pricing_section)[:PAIR_FIELD_COUNT]]
        if len(prices) == PAIR_FIELD_COUNT:
            pricing = {"input_per_mtok": prices[0], "output_per_mtok": prices[1]}
    values: dict[str, object] = {"context_length": _token_count(context.group(1)) if context else None}
    if pricing:
        values["pricing"] = pricing
    return ModelDocumentation(ids=ids, source=source, values={name: value for name, value in values.items() if value is not None})


def _documented_price(value: str) -> float | None:
    if value.lower() == "free":
        return 0.0
    match = re.fullmatch(r"\\?\$([\d.]+)", value)
    return float(match.group(1)) if match is not None else None


def _documented_flag(value: str) -> bool | None:
    return True if value.lower() == "yes" else False if value.lower() == "no" else None


def parse_together_models(document: str, source: str) -> tuple[ModelDocumentation, ...]:
    metadata = []
    html_rows = (_html_cells(row) for row in re.findall(r"<tr[^>]*>(.*?)</tr>", document, flags=re.DOTALL | re.IGNORECASE))
    markdown_rows = ([cell.strip() for cell in line.strip().strip("|").split("|")] for line in document.splitlines() if line.startswith("|"))
    for cells in (*html_rows, *markdown_rows):
        if len(cells) != TOGETHER_FIELD_COUNT or "/" not in cells[2]:
            continue
        prices = {
            "input_per_mtok": _documented_price(cells[4]),
            "cached_input_per_mtok": _documented_price(cells[5]),
            "output_per_mtok": _documented_price(cells[6]),
        }
        values: dict[str, object] = {
            "context_length": _token_count(cells[3]),
            "supports_tools": _documented_flag(cells[8]),
            "supports_structured_output": _documented_flag(cells[9]),
            "pricing": {name: price for name, price in prices.items() if price is not None},
        }
        metadata.append(
            ModelDocumentation(ids=(cells[2],), source=source, values={name: value for name, value in values.items() if value is not None})
        )
    return tuple(metadata)


def _html_cells(fragment: str) -> list[str]:
    return [html.unescape(re.sub(r"<[^>]+>", "", value)).strip() for value in re.findall(r"<td[^>]*>(.*?)</td>", fragment, flags=re.DOTALL)]


def _deepseek_rows(document: str, label: str) -> list[list[float]]:
    rows = re.findall(rf">{label}</td>(.*?)</tr>", document, flags=re.DOTALL | re.IGNORECASE)
    return [[float(amount) for amount in re.findall(r"\$([\d.]+)", row)] for row in rows]


def parse_deepseek_pricing(document: str, source: str) -> dict[str, ModelDocumentation]:
    model_row = re.search(r"<tr><td[^>]*>MODEL</td>(.*?)</tr>", document, flags=re.DOTALL | re.IGNORECASE)
    if model_row is None:
        message = f"DeepSeek pricing page has no model row: {source}"
        raise ValueError(message)
    models = _html_cells(model_row.group(1))
    context_match = re.search(r"CONTEXT LENGTH</td><td[^>]*>([^<]+)", document, flags=re.IGNORECASE)
    output_match = re.search(r"MAX OUTPUT</td><td[^>]*>(?:MAXIMUM:\s*)?([^<]+)", document, flags=re.IGNORECASE)
    off_peak = _deepseek_rows(document, "OFF-PEAK")
    peak = _deepseek_rows(document, "PEAK")
    if len(off_peak) != PRICE_FIELD_COUNT or len(peak) != PRICE_FIELD_COUNT or any(len(row) != len(models) for row in (*off_peak, *peak)):
        message = f"DeepSeek pricing page has an unrecognized rate matrix: {source}"
        raise ValueError(message)
    metadata = {}
    for index, model_id in enumerate(models):
        peak_price: dict[str, object] = {
            "input_per_mtok": peak[1][index],
            "cached_input_per_mtok": peak[0][index],
            "output_per_mtok": peak[2][index],
        }
        off_peak_price: dict[str, float] = {
            "input_per_mtok": off_peak[1][index],
            "cached_input_per_mtok": off_peak[0][index],
            "output_per_mtok": off_peak[2][index],
        }
        peak_price["tiers"] = {"off_peak": off_peak_price, "peak": dict(peak_price)}
        values: dict[str, object] = {
            "context_length": _token_count(context_match.group(1)) if context_match else None,
            "max_output_tokens": _token_count(output_match.group(1)) if output_match else None,
            "input_modalities": ["text", "image"] if "vision" in model_id else ["text"],
            "output_modalities": ["text"],
            "supports_tools": True,
            "supports_structured_output": True,
            "supports_thinking": True,
            "pricing": peak_price,
        }
        metadata[model_id] = ModelDocumentation(ids=(model_id,), source=source, values=values)
    return metadata


def _documentation_conflicts(model: dict[str, object], document: ModelDocumentation) -> list[str]:
    existing = model.get("source_conflicts")
    conflicts = [str(value) for value in existing] if isinstance(existing, list) else []
    for name in (
        "context_length",
        "max_output_tokens",
        "input_modalities",
        "output_modalities",
        "supports_tools",
        "supports_structured_output",
        "supports_thinking",
    ):
        current = model.get(name)
        documented = document.values.get(name)
        if current is not None and documented is not None and not _same_documented_value(current, documented):
            conflicts.append(f"{name}: provider API reports {current!r}; official documentation reports {documented!r}")
    current = model.get("pricing")
    documented = document.values.get("pricing")
    if isinstance(current, dict) and isinstance(documented, dict):
        current_pricing = cast("dict[str, object]", current)
        documented_pricing = cast("dict[str, object]", documented)
        differing = {
            name: (current_pricing[name], documented_pricing[name])
            for name in current_pricing.keys() & documented_pricing.keys()
            if not _same_documented_value(current_pricing[name], documented_pricing[name])
        }
        if differing:
            conflicts.append(f"pricing: provider API and official documentation differ on {differing!r}")
    documented_conflicts = document.values.get("source_conflicts")
    if isinstance(documented_conflicts, list):
        conflicts.extend(str(value) for value in documented_conflicts)
    return list(dict.fromkeys(conflicts))


def _same_documented_value(current: object, documented: object) -> bool:
    if (
        isinstance(current, (int, float))
        and not isinstance(current, bool)
        and isinstance(documented, (int, float))
        and not isinstance(documented, bool)
    ):
        return math.isclose(float(current), float(documented), rel_tol=0, abs_tol=1e-9)
    return current == documented


def apply_documentation(models: list[dict[str, object]], documents: tuple[ModelDocumentation, ...]) -> list[dict[str, object]]:
    by_id = {model_id: document for document in documents for model_id in document.ids}
    for model in models:
        aliases = model.get("aliases")
        alias_names = (str(name) for name in aliases) if isinstance(aliases, list) else ()
        document = by_id.get(str(model.get("id"))) or next((by_id[name] for name in alias_names if name in by_id), None)
        if document is None:
            continue
        conflicts = _documentation_conflicts(model, document)
        for name, source_name in (("context_length", "context_source"), ("max_output_tokens", "max_output_source")):
            if model.get(name) is None and document.values.get(name) is not None:
                model[name] = document.values[name]
                model[source_name] = "vendor-docs"
        for name in ("input_modalities", "output_modalities", "supports_tools", "supports_structured_output", "supports_thinking"):
            if model.get(name) is None and document.values.get(name) is not None:
                model[name] = document.values[name]
        if model.get("pricing") is None and document.values.get("pricing") is not None:
            model["pricing"] = document.values["pricing"]
            model["pricing_source"] = "vendor-docs"
        if conflicts:
            model["source_conflicts"] = conflicts
        model["documentation_url"] = document.source
    return models
