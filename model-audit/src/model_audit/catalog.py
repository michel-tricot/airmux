from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import yaml

from model_audit.models import Catalog, EgressKind, Target

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


SURFACES: dict[str, tuple[str, str, EgressKind]] = {
    "oai": ("oai", "chat/completions", "openai_compatible"),
    "oai_responses": ("oai_responses", "responses", "openai_responses"),
    "anthropic": ("anthropic", "messages", "anthropic"),
}


def _surfaces(provider: Mapping[str, object]) -> tuple[Surface, ...]:
    ingresses = [str(value) for value in _sequence(provider.get("ingress"))]
    auths = [str(value) for value in _sequence(provider.get("auth"))]
    surfaces = []
    for index, ingress in enumerate(ingresses):
        definition = SURFACES.get(ingress)
        if definition is None:
            continue
        surface_id, endpoint, kind = definition
        auth = auths[index] if len(auths) == len(ingresses) else auths[0]
        surfaces.append(Surface(id=surface_id, endpoint=endpoint, kind=kind, auth=auth, headers={}))
    return tuple(surfaces)


def _models(taxonomy: Path, provider_id: str) -> tuple[Mapping[str, object], ...]:
    path = taxonomy / "models" / f"{provider_id}.json"
    if not path.exists():
        return ()
    document = _mapping(json.loads(path.read_text(encoding="utf-8")))
    return tuple(_mapping(item) for item in _sequence(document.get("models")))


def _target(provider: Mapping[str, object], model: Mapping[str, object], surface: Surface) -> Target:
    provider_id = str(provider["id"])
    context = model.get("context_length")
    return Target(
        provider_id=provider_id,
        surface_id=surface.id,
        endpoint=surface.endpoint,
        egress_kind=surface.kind,
        base_url=str(provider["base_url"]),
        credential_env=str(provider["env_var"]),
        auth=surface.auth,
        headers=surface.headers,
        model_id=f"{provider_id}/{model['id']}",
        upstream_model=str(model.get("upstream_id") or model["id"]),
        context_window=context if isinstance(context, int) else 0,
        max_output_tokens=cast("int | None", model.get("max_output_tokens")),
    )


def _target_key(target: Target) -> tuple[str, str, str]:
    return target.provider_id, target.model_id, target.surface_id


def load_catalog(taxonomy: Path) -> Catalog:
    provider_document = _mapping(yaml.safe_load((taxonomy / "providers.yml").read_text(encoding="utf-8")))
    providers = tuple(_mapping(item) for item in _sequence(provider_document.get("providers")))
    targets: tuple[Target, ...] = tuple(
        _target(provider, model, surface)
        for provider in sorted(providers, key=lambda item: str(item.get("id")))
        for model in _models(taxonomy, str(provider["id"]))
        for surface in _surfaces(provider)
    )
    return Catalog(targets=tuple(sorted(targets, key=_target_key)))
