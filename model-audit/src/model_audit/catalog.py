from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import yaml

from model_audit.models import Catalog, EgressKind, Target
from model_audit.surfaces import discover

if TYPE_CHECKING:
    from pathlib import Path


def _mapping(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


@dataclass(frozen=True)
class Surface:
    id: str
    endpoint: str
    kind: EgressKind
    auth: str
    headers: dict[str, str]


def _surfaces(provider: Mapping[str, object]) -> tuple[Surface, ...]:
    ingresses = [str(value) for value in _sequence(provider.get("ingress"))]
    auths = [str(value) for value in _sequence(provider.get("auth"))]
    surfaces = []
    for index, ingress in enumerate(ingresses):
        definition = discover().get(ingress)
        if definition is None:
            continue
        auth = auths[index] if len(auths) == len(ingresses) else auths[0]
        surfaces.append(Surface(id=definition.id, endpoint=definition.endpoint, kind=definition.kind, auth=auth, headers={}))
    return tuple(surfaces)


def _models(taxonomy: Path, provider_id: str) -> tuple[Mapping[str, object], ...]:
    path = taxonomy / "models" / f"{provider_id}.json"
    if not path.exists():
        return ()
    document = _mapping(json.loads(path.read_text(encoding="utf-8")))
    return tuple(_mapping(item) for item in _sequence(document.get("models")))


def _target(provider: Mapping[str, object], model: Mapping[str, object], surface: Surface, gateway_egress_kind: EgressKind) -> Target:
    provider_id = str(provider["id"])
    context = model.get("context_length")
    return Target(
        provider_id=provider_id,
        surface_id=surface.id,
        endpoint=surface.endpoint,
        egress_kind=surface.kind,
        gateway_egress_kind=gateway_egress_kind,
        base_url=str(provider["base_url"]),
        credential_env=str(provider["env_var"]),
        auth=surface.auth,
        headers=surface.headers,
        param_aliases={str(name): str(alias) for name, alias in _mapping(provider.get("param_aliases")).items()},
        model_id=f"{provider_id}/{model['id']}",
        upstream_model=str(model.get("upstream_id") or model["id"]),
        context_window=context if isinstance(context, int) else 0,
        max_output_tokens=cast("int | None", model.get("max_output_tokens")),
    )


def _target_key(target: Target) -> tuple[str, str, str]:
    return target.provider_id, target.model_id, target.surface_id


def _gateway_egress_kinds(taxonomy: Path) -> dict[str, EgressKind]:
    document = _mapping(yaml.safe_load((taxonomy / "taxonomy.yml").read_text(encoding="utf-8")))
    providers = {
        str(provider["provider_id"]): cast("EgressKind", provider["kind"])
        for value in _sequence(document.get("providers"))
        if (provider := _mapping(value)).get("provider_id") is not None
        and provider.get("kind") in {"openai_compatible", "openai_responses", "anthropic"}
    }
    return {
        str(model["model_id"]): cast("EgressKind", model.get("egress_kind") or providers[str(model["provider_id"])])
        for value in _sequence(document.get("models"))
        if (model := _mapping(value)).get("model_id") is not None and str(model.get("provider_id")) in providers
    }


def load_catalog(taxonomy: Path) -> Catalog:
    provider_document = _mapping(yaml.safe_load((taxonomy / "providers.yml").read_text(encoding="utf-8")))
    providers = tuple(_mapping(item) for item in _sequence(provider_document.get("providers")))
    gateway_egress_kinds = _gateway_egress_kinds(taxonomy)
    targets: tuple[Target, ...] = tuple(
        _target(provider, model, surface, gateway_egress_kinds[f"{provider['id']}/{model['id']}"])
        for provider in sorted(providers, key=lambda item: str(item.get("id")))
        for model in _models(taxonomy, str(provider["id"]))
        if f"{provider['id']}/{model['id']}" in gateway_egress_kinds
        for surface in _surfaces(provider)
    )
    return Catalog(targets=tuple(sorted(targets, key=_target_key)))
