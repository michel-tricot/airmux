from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .types import is_object, object_or_empty, required_string, strings, value_list

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from .types import CatalogObject, CatalogValue

MAX_REFERENCE_HOPS = 20
MAX_DISCOVERY_DEPTH = 2

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


def _deref(node: CatalogValue, definitions: Mapping[str, CatalogValue], seen: frozenset[str]) -> CatalogValue:
    hops = 0
    while isinstance(node, dict) and hops < MAX_REFERENCE_HOPS:
        reference = node.get("$ref")
        if not isinstance(reference, str):
            break
        key = reference.removeprefix("#/$defs/")
        if key in seen:
            return None
        seen = seen | {key}
        node = definitions.get(key)
        hops += 1
    return node


def _variants(node: CatalogValue, definitions: Mapping[str, CatalogValue], seen: frozenset[str]) -> list[CatalogObject]:
    variants: list[CatalogObject] = []
    queue = [node]
    budget = 40
    while queue and budget > 0:
        budget -= 1
        current = _deref(queue.pop(), definitions, seen)
        if not is_object(current):
            continue
        if current.get("properties") or current.get("items") is not None:
            variants.append(current)
        for keyword in ("oneOf", "anyOf", "allOf"):
            nested = current.get(keyword)
            queue.extend(value_list(nested))
    return variants


def _walk_paths(  # noqa: PLR0913,PLR0917 recursive schema traversal keeps its state explicit
    node: CatalogValue,
    definitions: Mapping[str, CatalogValue],
    prefix: str,
    depth: int,
    paths: set[str],
    seen: frozenset[str] = frozenset(),
) -> None:
    if depth > MAX_DISCOVERY_DEPTH:
        return
    for variant in _variants(node, definitions, seen):
        for name, child in object_or_empty(variant.get("properties")).items():
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


def discovery_evidence(provider: Mapping[str, CatalogValue], taxonomy: Path) -> CatalogObject:
    sources = []
    support = {}
    completion = object_or_empty(object_or_empty(provider.get("schema")).get("completion"))
    for ingress in strings(provider.get("ingress")):
        if ingress not in INGRESS_ENDPOINT or ingress not in completion:
            continue
        source = required_string(object_or_empty(completion[ingress]).get("request"), f"{ingress} request schema")
        paths = schema_paths(taxonomy / source)
        endpoint_support = {parameter: "supported" for parameter, path in PARAMETER_PATHS[ingress].items() if path in paths}
        sources.append(source)
        support[INGRESS_ENDPOINT[ingress]] = endpoint_support
    return {"sources": sorted(sources), "support": support}


def apply_discovery_evidence(models: list[CatalogObject], evidence: CatalogObject) -> list[CatalogObject]:
    for model in models:
        for field in ("reachable", "reachable_checked", "endpoint_status"):
            model.pop(field, None)
        model["parameter_evidence"] = {"model_discovery": evidence}
    return models
