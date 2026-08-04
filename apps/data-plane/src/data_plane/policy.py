from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from contract import BundleV1, KeyEntry, ModelEntry, ProviderEntry
    from data_plane.canonical import CanonicalRequest


@dataclass(frozen=True)
class Allow:
    model: ModelEntry
    provider: ProviderEntry


@dataclass(frozen=True)
class Deny:
    reason: str
    status: int


type Decision = Allow | Deny


def evaluate(req: CanonicalRequest, key: KeyEntry, bundle: BundleV1, now: datetime) -> Decision:  # noqa: ARG001 now is spec-fixed, staleness enforced at swap time
    """Pure and synchronous: no async, no network, no I/O, no datetime.now(). Under 100 lines."""
    model = next((m for m in bundle.catalog.models if m.model_id == req.model), None)
    if model is None:
        return Deny(reason="unknown_model", status=404)
    if "*" not in key.allowed_models and req.model not in key.allowed_models:
        return Deny(reason="model_not_allowed", status=403)
    provider = next((p for p in bundle.catalog.providers if p.provider_id == model.provider_id), None)
    if provider is None:
        return Deny(reason="provider_not_configured", status=502)
    return Allow(model=model, provider=provider)
