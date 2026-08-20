from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import yaml

from provider_parity.models import Catalog, EgressKind, Support, Target

if TYPE_CHECKING:
    from pathlib import Path


def _mapping(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _strings(value: object) -> frozenset[str]:
    return frozenset(item for item in _sequence(value) if isinstance(item, str))


def _support(evidence: object, endpoint: str, metadata: Mapping[str, object], applied: Mapping[str, object]) -> frozenset[str]:
    evidence_map = _mapping(evidence)
    discovery = _mapping(_mapping(evidence_map.get("model_discovery")).get("support"))
    live = _mapping(_mapping(evidence_map.get("live_probe")).get("support"))
    resolved = {str(name): str(status) for name, status in _mapping(discovery.get(endpoint)).items()}
    resolved.update({str(name): str(status) for name, status in _mapping(live.get(endpoint)).items()})
    if isinstance(metadata.get("supports_tools"), bool):
        resolved["tools"] = "supported" if metadata["supports_tools"] else "unsupported"
    if metadata.get("supports_structured_output") is True:
        resolved["json_object"] = "supported"
        resolved["json_schema"] = "supported"
    if metadata.get("supports_thinking") is True:
        resolved["reasoning"] = "supported"
    if resolved.get("parallel_tools") == "supported":
        resolved["tools"] = "supported"
    for capability in _strings(applied.get("capabilities")):
        resolved.setdefault(capability, "supported")
    return frozenset(name for name, status in resolved.items() if status == "supported")


def _parameter_support(evidence: object, endpoint: str) -> dict[str, Support]:
    evidence_map = _mapping(evidence)
    discovery = _mapping(_mapping(evidence_map.get("model_discovery")).get("support"))
    live = _mapping(_mapping(evidence_map.get("live_probe")).get("support"))
    resolved = {str(name): str(status) for name, status in _mapping(discovery.get(endpoint)).items()}
    resolved.update({str(name): str(status) for name, status in _mapping(live.get(endpoint)).items()})
    return {name: status for name, status in sorted(resolved.items()) if status in {"supported", "unsupported"}}


def _egress_kind(value: object) -> EgressKind:
    if value not in {"openai_compatible", "openai_responses", "anthropic"}:
        message = f"unknown egress kind {value!r}"
        raise ValueError(message)
    return cast("EgressKind", value)


@dataclass(frozen=True)
class _Surface:
    id: str
    endpoint: str
    kind: EgressKind
    auth: str
    headers: dict[str, str]


_LEGACY_SURFACES: dict[EgressKind, tuple[str, str]] = {
    "openai_compatible": ("oai", "chat/completions"),
    "openai_responses": ("oai_responses", "responses"),
    "anthropic": ("anthropic", "messages"),
}


def _surfaces(provider: Mapping[str, object], applied_provider: Mapping[str, object], model: Mapping[str, object]) -> tuple[_Surface, ...]:
    explicit = _mapping(provider.get("surfaces"))
    if explicit:
        return tuple(
            _Surface(
                id=str(surface_id),
                endpoint=str(surface["endpoint"]),
                kind=_egress_kind(surface["egress_kind"]),
                auth=str(surface["auth"]),
                headers={str(name): str(value) for name, value in _mapping(surface.get("headers")).items()},
            )
            for surface_id, value in sorted(explicit.items())
            if (surface := _mapping(value))
        )
    kind = _egress_kind(model.get("egress_kind") or applied_provider.get("kind"))
    surface_id, endpoint = _LEGACY_SURFACES[kind]
    ingresses = [str(value) for value in _sequence(provider.get("ingress"))]
    if surface_id not in ingresses:
        return ()
    auths = [str(value) for value in _sequence(provider.get("auth"))]
    auth = auths[ingresses.index(surface_id)] if len(auths) == len(ingresses) else auths[0]
    return (_Surface(id=surface_id, endpoint=endpoint, kind=kind, auth=auth, headers={}),)


def _target_key(target: Target) -> tuple[str, str, str]:
    return target.provider_id, target.surface_id, target.model_id


def _modalities(model: Mapping[str, object], endpoint: str, applied: Mapping[str, object]) -> frozenset[str]:
    modalities = set(_strings(applied.get("input_modalities")) or _strings(model.get("input_modalities")) or {"text"})
    live = _mapping(_mapping(_mapping(model.get("capability_evidence")).get("live_probe")).get("support"))
    image = _mapping(live.get(endpoint)).get("image_input")
    if image == "supported":
        modalities.add("image")
    elif image == "unsupported":
        modalities.discard("image")
    return frozenset(modalities)


def _models_by_id(taxonomy: Path, provider_id: str) -> dict[str, Mapping[str, object]]:
    document = json.loads((taxonomy / "models" / f"{provider_id}.json").read_text(encoding="utf-8"))
    return {str(model["id"]): model for item in _sequence(_mapping(document).get("models")) if (model := _mapping(item)).get("id")}


def load_catalog(taxonomy: Path) -> Catalog:
    research = yaml.safe_load((taxonomy / "providers.yml").read_text(encoding="utf-8"))
    applied = yaml.safe_load((taxonomy / "taxonomy.yml").read_text(encoding="utf-8"))
    providers = {str(provider["id"]): provider for item in _sequence(_mapping(research).get("providers")) if (provider := _mapping(item)).get("id")}
    applied_providers = {
        str(provider["provider_id"]): provider
        for item in _sequence(_mapping(applied).get("providers"))
        if (provider := _mapping(item)).get("provider_id")
    }
    applied_models = [_mapping(item) for item in _sequence(_mapping(applied).get("models"))]
    targets: list[Target] = []
    for provider_id, provider in sorted(providers.items()):
        provider_models = [model for model in applied_models if model.get("provider_id") == provider_id]
        if not provider_models:
            continue
        raw_models = _models_by_id(taxonomy, provider_id)
        applied_provider = applied_providers[provider_id]
        for applied_model in provider_models:
            for surface in _surfaces(provider, applied_provider, applied_model):
                endpoint = surface.endpoint
                upstream = str(applied_model["upstream_model"])
                raw_id = str(applied_model["model_id"]).removeprefix(f"{provider_id}/")
                raw_model = raw_models.get(raw_id)
                if raw_model is None:
                    raw_model = next((model for model in raw_models.values() if model.get("upstream_id") == upstream), None)
                if raw_model is None:
                    continue
                status = _mapping(_mapping(raw_model.get("endpoint_status")).get(endpoint))
                if status.get("outcome") != "ok":
                    continue
                targets.append(
                    Target(
                        provider_id=provider_id,
                        surface_id=surface.id,
                        endpoint=endpoint,
                        egress_kind=surface.kind,
                        base_url=str(provider["base_url"]),
                        credential_env=str(provider["env_var"]),
                        auth=surface.auth,
                        headers=surface.headers,
                        model_id=str(applied_model["model_id"]),
                        upstream_model=upstream,
                        context_window=int(cast("int", applied_model["context_window"])),
                        max_output_tokens=cast("int | None", applied_model.get("max_output_tokens")),
                        input_modalities=_modalities(raw_model, endpoint, applied_model),
                        capabilities=_support(raw_model.get("capability_evidence"), endpoint, raw_model, applied_model),
                        parameter_support=_parameter_support(raw_model.get("parameter_evidence"), endpoint),
                    )
                )
    return Catalog(targets=tuple(sorted(targets, key=_target_key)))
