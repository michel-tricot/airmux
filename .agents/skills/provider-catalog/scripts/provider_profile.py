from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

Ingress = Literal["oai", "oai_responses", "anthropic"]
Endpoint = Literal["chat/completions", "responses", "messages"]
EgressKind = Literal["openai_compatible", "openai_responses", "anthropic"]

INGRESS_ENDPOINT: dict[Ingress, Endpoint] = {
    "oai": "chat/completions",
    "oai_responses": "responses",
    "anthropic": "messages",
}
ENDPOINT_INGRESS = {endpoint: ingress for ingress, endpoint in INGRESS_ENDPOINT.items()}
INGRESS_EGRESS_KIND: dict[Ingress, EgressKind] = {
    "oai": "openai_compatible",
    "oai_responses": "openai_responses",
    "anthropic": "anthropic",
}


@dataclass(frozen=True)
class SurfaceProfile:
    ingress: Ingress
    endpoint: Endpoint
    auth: str
    egress_kind: EgressKind
    headers: dict[str, str]


def _strings(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("expected a list of strings")
    return cast(list[str], value)


def provider_id(provider: Mapping[str, object]) -> str:
    value = provider.get("id")
    if not isinstance(value, str) or not value:
        raise ValueError("provider has no id")
    return value


def provider_surfaces(provider: Mapping[str, object]) -> tuple[SurfaceProfile, ...]:
    configured = provider.get("surfaces")
    if not isinstance(configured, Mapping):
        raise ValueError(f"{provider_id(provider)} has no surface profiles")
    surfaces: list[SurfaceProfile] = []
    for raw_ingress in _strings(provider.get("ingress")):
        if raw_ingress not in INGRESS_ENDPOINT:
            continue
        ingress = raw_ingress
        raw_surface = configured.get(ingress)
        if not isinstance(raw_surface, Mapping):
            raise ValueError(f"{provider_id(provider)}/{ingress} has no surface profile")
        endpoint = raw_surface.get("endpoint")
        auth = raw_surface.get("auth")
        egress_kind = raw_surface.get("egress_kind")
        headers = raw_surface.get("headers") or {}
        if endpoint != INGRESS_ENDPOINT[ingress]:
            raise ValueError(f"{provider_id(provider)}/{ingress} has endpoint {endpoint!r}")
        if not isinstance(auth, str) or not auth:
            raise ValueError(f"{provider_id(provider)}/{ingress} has no auth profile")
        if egress_kind != INGRESS_EGRESS_KIND[ingress]:
            raise ValueError(f"{provider_id(provider)}/{ingress} has egress kind {egress_kind!r}")
        if not isinstance(headers, Mapping) or not all(isinstance(key, str) and isinstance(value, str) for key, value in headers.items()):
            raise ValueError(f"{provider_id(provider)}/{ingress} has invalid headers")
        surfaces.append(
            SurfaceProfile(
                ingress=ingress,
                endpoint=cast(Endpoint, endpoint),
                auth=auth,
                egress_kind=cast(EgressKind, egress_kind),
                headers=cast(dict[str, str], dict(headers)),
            )
        )
    return tuple(surfaces)


def surface_for_endpoint(provider: Mapping[str, object], endpoint: str) -> SurfaceProfile:
    for surface in provider_surfaces(provider):
        if surface.endpoint == endpoint:
            return surface
    raise ValueError(f"{provider_id(provider)} does not expose {endpoint}")


def endpoints(provider: Mapping[str, object]) -> tuple[Endpoint, ...]:
    return tuple(surface.endpoint for surface in provider_surfaces(provider))


def auth_headers(auth: str, key: str) -> dict[str, str]:
    if auth == "bearer":
        return {"Authorization": f"Bearer {key}"}
    if auth.startswith("header_key:"):
        return {auth.split(":", 1)[1]: key}
    raise ValueError(f"unsupported credential transport {auth!r}")


def inference_headers(provider: Mapping[str, object], endpoint: str, key: str) -> dict[str, str]:
    surface = surface_for_endpoint(provider, endpoint)
    return {**auth_headers(surface.auth, key), **surface.headers}


def catalog_headers(provider: Mapping[str, object], key: str | None) -> dict[str, str]:
    auth = provider.get("models_auth")
    if not isinstance(auth, str):
        raise ValueError(f"{provider_id(provider)} has no models_auth")
    if auth != "none" and key is None:
        raise ValueError(f"{provider_id(provider)} requires a model-catalog credential")
    credentials = {} if auth == "none" else auth_headers(auth, key or "")
    configured = provider.get("models_headers") or {}
    if not isinstance(configured, Mapping) or not all(isinstance(name, str) and isinstance(value, str) for name, value in configured.items()):
        raise ValueError(f"{provider_id(provider)} has invalid model-catalog headers")
    return {**credentials, **cast(dict[str, str], dict(configured))}


def inference_url(provider: Mapping[str, object], endpoint: str) -> str:
    base_url = provider.get("base_url")
    if not isinstance(base_url, str) or not base_url:
        raise ValueError(f"{provider_id(provider)} has no base_url")
    surface_for_endpoint(provider, endpoint)
    return f"{base_url.rstrip('/')}/{endpoint}"


def select_provider_ids(wanted: set[str], known: set[str]) -> set[str]:
    unknown = wanted - known
    if unknown:
        raise ValueError(f"unknown providers: {', '.join(sorted(unknown))}")
    return wanted or known
