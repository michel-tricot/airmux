from __future__ import annotations

from collections.abc import Mapping

from parameter_support import INGRESS_ENDPOINT

PROBES = frozenset({"streaming", "image_input", "tools", "parallel_tools", "json_object", "json_schema", "reasoning"})
CAPABILITIES = PROBES - {"image_input"}
SUPPORT = frozenset({"supported", "unsupported"})
CAPABILITY_ORDER = ("streaming", "tools", "parallel_tools", "json_object", "json_schema", "reasoning")


def _live_support(model: Mapping, endpoint: str) -> dict[str, str]:
    evidence = model.get("capability_evidence") or {}
    support = ((evidence.get("live_probe") or {}).get("support") or {}).get(endpoint) or {}
    return {name: status for name, status in support.items() if name in PROBES and status in SUPPORT}


def discovery_evidence(provider: Mapping) -> dict:
    sources = []
    support = {}
    completion = (provider.get("schema") or {}).get("completion") or {}
    for ingress in provider.get("ingress") or []:
        if ingress not in INGRESS_ENDPOINT or ingress not in completion:
            continue
        stream = completion[ingress].get("stream")
        if stream:
            sources.append(stream)
            support[INGRESS_ENDPOINT[ingress]] = {"streaming": "supported"}
    return {"sources": sorted(sources), "support": support}


def apply_discovery_evidence(models: list[dict], evidence: dict) -> list[dict]:
    for model in models:
        live_probe = (model.get("capability_evidence") or {}).get("live_probe")
        model["capability_evidence"] = {
            "model_discovery": evidence,
            **({"live_probe": live_probe} if live_probe else {}),
        }
    return models


def resolve_capabilities(model: Mapping, endpoint: str) -> list[str]:
    evidence = model.get("capability_evidence") or {}
    support = dict(((evidence.get("model_discovery") or {}).get("support") or {}).get(endpoint) or {})
    if model.get("supports_tools") is not None:
        support["tools"] = "supported" if model["supports_tools"] else "unsupported"
    support.update(_live_support(model, endpoint))
    if support.get("parallel_tools") == "supported":
        support["tools"] = "supported"
    return [capability for capability in CAPABILITY_ORDER if support.get(capability) == "supported"]


def resolve_input_modalities(model: Mapping, endpoint: str) -> list[str]:
    modalities = list(model.get("input_modalities") or ["text"])
    image_support = _live_support(model, endpoint).get("image_input")
    if image_support == "supported" and "image" not in modalities:
        modalities.append("image")
    if image_support == "unsupported":
        modalities = [modality for modality in modalities if modality != "image"]
    return [modality for modality in ("text", "image") if modality in modalities]


def resolve_output_modalities(model: Mapping) -> list[str]:
    modalities = list(model.get("output_modalities") or ["text"])
    return [modality for modality in ("text", "image", "audio", "video") if modality in modalities]
