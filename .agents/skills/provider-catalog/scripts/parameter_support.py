from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from probe_runtime import Support
from provider_profile import INGRESS_ENDPOINT

SUPPORT = frozenset({"supported", "unsupported"})
ENDPOINTS = frozenset(INGRESS_ENDPOINT.values())
PARAMETER_PATHS = {
    "oai": {
        "temperature": "$.temperature",
        "top_p": "$.top_p",
        "stop": "$.stop",
        "seed": "$.seed",
        "reasoning_effort": "$.reasoning_effort",
        "parallel_tool_calls": "$.parallel_tool_calls",
        "logprobs": "$.logprobs",
    },
    "oai_responses": {
        "temperature": "$.temperature",
        "top_p": "$.top_p",
        "stop": "$.stop",
        "seed": "$.seed",
        "reasoning_effort": "$.reasoning.effort",
        "parallel_tool_calls": "$.parallel_tool_calls",
        "logprobs": "$.logprobs",
    },
    "anthropic": {
        "temperature": "$.temperature",
        "top_p": "$.top_p",
        "stop": "$.stop_sequences",
        "seed": "$.seed",
        "reasoning_effort": "$.reasoning_effort",
        "parallel_tool_calls": "$.parallel_tool_calls",
        "logprobs": "$.logprobs",
    },
}
PARAMETERS = frozenset(parameter for mappings in PARAMETER_PATHS.values() for parameter in mappings)


def _deref(node: object, definitions: Mapping, seen: frozenset[str]) -> object:
    hops = 0
    while isinstance(node, Mapping) and isinstance(node.get("$ref"), str) and hops < 20:
        key = str(node.get("$ref")).removeprefix("#/$defs/")
        if key in seen:
            return None
        seen = seen | {key}
        node = definitions.get(key)
        hops += 1
    return node


def _variants(node: object, definitions: Mapping, seen: frozenset[str]) -> list[dict]:
    variants = []
    queue = [node]
    budget = 40
    while queue and budget > 0:
        budget -= 1
        current = _deref(queue.pop(), definitions, seen)
        if not isinstance(current, dict):
            continue
        if current.get("properties") or current.get("items") is not None:
            variants.append(current)
        for keyword in ("oneOf", "anyOf", "allOf"):
            children = current.get(keyword)
            if isinstance(children, list):
                queue.extend(children)
    return variants


def _walk_paths(node: object, definitions: Mapping, prefix: str, depth: int, paths: set[str], seen: frozenset[str] = frozenset()) -> None:
    if depth > 2:
        return
    for variant in _variants(node, definitions, seen):
        for name, child in (variant.get("properties") or {}).items():
            path = f"{prefix}.{name}"
            paths.add(path)
            _walk_paths(child, definitions, path, depth + 1, paths, seen)
        if variant.get("items") is not None:
            _walk_paths(variant["items"], definitions, f"{prefix}[*]", depth, paths, seen)


def schema_paths(path: Path) -> set[str]:
    schema = json.loads(path.read_text())
    paths: set[str] = set()
    _walk_paths({key: value for key, value in schema.items() if key != "$defs"}, schema.get("$defs") or {}, "$", 0, paths)
    return paths


def discovery_evidence(provider: Mapping, taxonomy: Path) -> dict:
    sources = []
    support = {}
    completion = (provider.get("schema") or {}).get("completion") or {}
    for ingress in provider.get("ingress") or []:
        if ingress not in INGRESS_ENDPOINT or ingress not in completion:
            continue
        source = completion[ingress]["request"]
        paths = schema_paths(taxonomy / source)
        endpoint_support = {parameter: "supported" for parameter, path in PARAMETER_PATHS[ingress].items() if path in paths}
        sources.append(source)
        support[INGRESS_ENDPOINT[ingress]] = endpoint_support
    return {"sources": sorted(sources), "support": support}


def apply_discovery_evidence(models: list[dict], evidence: dict) -> list[dict]:
    for model in models:
        live_probe = (model.get("parameter_evidence") or {}).get("live_probe")
        model["parameter_evidence"] = {
            "model_discovery": evidence,
            **({"live_probe": live_probe} if live_probe else {}),
        }
    return models


def resolve_parameter_support(evidence: Mapping, endpoint: str) -> dict[str, str]:
    resolved = dict(((evidence.get("model_discovery") or {}).get("support") or {}).get(endpoint) or {})
    resolved.update(((evidence.get("live_probe") or {}).get("support") or {}).get(endpoint) or {})
    return {parameter: status for parameter, status in sorted(resolved.items()) if status in SUPPORT}


def classify_parameter_response(status: int, body: str, parameter: str) -> Support | None:
    if 200 <= status < 300:
        return "supported"
    if status != 400:
        return None
    try:
        payload = json.loads(body)
        message = str((payload.get("error") or {}).get("message") or payload)
    except (json.JSONDecodeError, AttributeError):
        message = body
    lowered = message.casefold()
    spellings = (parameter, parameter.replace("_", " "), parameter.replace("_", "."))
    named = any(spelling.casefold() in lowered for spelling in spellings)
    rejected = "unsupported parameter" in lowered or "not supported" in lowered or "does not support" in lowered
    return "unsupported" if named and rejected else None
