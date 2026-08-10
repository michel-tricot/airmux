from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from data_plane.credentials import candidates_for

if TYPE_CHECKING:
    from datetime import datetime

    from contract import CredentialEntry, KeyEntry, ModelEntry, ProviderEntry
    from data_plane.canonical import CanonicalRequest
    from data_plane.holder import BundleSnapshot


@dataclass(frozen=True)
class Allow:
    model: ModelEntry
    provider: ProviderEntry
    candidates: tuple[CredentialEntry, ...]


@dataclass(frozen=True)
class Deny:
    reason: str
    status: int


type Decision = Allow | Deny


def evaluate(req: CanonicalRequest, key: KeyEntry, snap: BundleSnapshot, now: datetime) -> Decision:  # noqa: ARG001 now is spec-fixed, staleness enforced at swap time
    """Pure and synchronous: no async, no network, no I/O, no datetime.now(). Under 100 lines.

    Returns the credentials that may be spent rather than a choice between them: picking one means
    knowing which are in cooldown, which is state, and state does not belong in a pure function.
    """
    model = next((m for m in snap.bundle.catalog.models if m.model_id == req.model), None)
    if model is None:
        return Deny(reason="unknown_model", status=404)
    provider = next((p for p in snap.bundle.catalog.providers if p.provider_id == model.provider_id), None)
    if provider is None:
        return Deny(reason="provider_not_configured", status=502)
    candidates = candidates_for(snap.credential_index, key.workspace_id, key.org_id, provider.provider_id)
    if not candidates:
        return Deny(reason="credential_unavailable", status=402)
    return Allow(model=model, provider=provider, candidates=candidates)
