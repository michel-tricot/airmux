from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

INGRESS_ENDPOINT = {"oai": "chat/completions", "oai_responses": "responses", "anthropic": "messages"}
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
def _deref(node: object, definitions: Mapping, seen: frozenset[str]) -> object:
    hops = 0
    while isinstance(node, dict) and "$ref" in node and hops < 20:
        key = str(node["$ref"]).removeprefix("#/$defs/")
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
            queue.extend(current.get(keyword) or [])
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
        for field in ("reachable", "reachable_checked", "endpoint_status"):
            model.pop(field, None)
        model["parameter_evidence"] = {"model_discovery": evidence}
    return models
