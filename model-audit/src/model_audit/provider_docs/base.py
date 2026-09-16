from __future__ import annotations

import html
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import cast

import httpx

USER_AGENT = {"User-Agent": "airmux-taxonomy/1.0", "Accept": "text/markdown,text/plain,text/html"}


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


def token_count(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*([\d,.]+)\s*([KMB]?)\s*(?:tokens?)?\s*", value, flags=re.IGNORECASE)
    if match is None:
        return None
    scale = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[match.group(2).upper()]
    return int(float(match.group(1).replace(",", "")) * scale)


def documented_price(value: str) -> float | None:
    if value.lower() == "free":
        return 0.0
    match = re.fullmatch(r"\\?\$([\d.]+)", value)
    return float(match.group(1)) if match is not None else None


def documented_flag(value: str) -> bool | None:
    return True if value.lower() == "yes" else False if value.lower() == "no" else None


def html_cells(fragment: str) -> list[str]:
    return [html.unescape(re.sub(r"<[^>]+>", "", value)).strip() for value in re.findall(r"<td[^>]*>(.*?)</td>", fragment, flags=re.DOTALL)]


def markdown_price(markdown: str, label: str) -> float | None:
    match = re.search(rf"\|\s*(?:\[)?{re.escape(label)}(?:\]\([^)]+\))?\s*\|\s*\\?\$([\d.]+)", markdown, flags=re.IGNORECASE)
    return float(match.group(1)) if match is not None else None


def markdown_modalities(markdown: str, label: str) -> list[str] | None:
    match = re.search(rf"^-\s*{re.escape(label)} modalities:\s*(.+)$", markdown, flags=re.MULTILINE | re.IGNORECASE)
    return [value.strip() for value in match.group(1).split(",")] if match is not None else None


def _same_documented_value(current: object, documented: object) -> bool:
    if (
        isinstance(current, (int, float))
        and not isinstance(current, bool)
        and isinstance(documented, (int, float))
        and not isinstance(documented, bool)
    ):
        return math.isclose(float(current), float(documented), rel_tol=0, abs_tol=1e-9)
    return current == documented


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
