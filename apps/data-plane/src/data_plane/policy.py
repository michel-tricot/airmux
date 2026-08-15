from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from data_plane.credentials import candidates_for

if TYPE_CHECKING:
    from contract import CredentialEntry, KeyEntry, ModelEntry, ProviderEntry
    from data_plane.bundle.holder import BundleSnapshot
    from data_plane.canonical import CanonicalRequest
    from data_plane.profiles import CompiledProfile


@dataclass(frozen=True)
class Allow:
    model: ModelEntry
    provider: ProviderEntry
    candidates: tuple[CredentialEntry, ...]
    profile: CompiledProfile


@dataclass(frozen=True)
class Deny:
    reason: str
    status: int


type Decision = Allow | Deny


def evaluate(req: CanonicalRequest, key: KeyEntry, snap: BundleSnapshot) -> Decision:
    """Pure and synchronous: no async, no network, no I/O, no datetime.now(). Under 100 lines.

    Returns the credentials that may be spent rather than a choice between them: picking one means
    knowing which are in cooldown, which is state, and state does not belong in a pure function.
    """
    model = snap.model_index.get(req.model)
    if model is None:
        return Deny(reason="unknown_model", status=404)
    provider = snap.provider_index.get(model.provider_id)
    if provider is None:
        return Deny(reason="provider_not_configured", status=502)
    candidates = candidates_for(snap.credential_index, key.workspace_id, key.org_id, provider.provider_id)
    if not candidates:
        return Deny(reason="credential_unavailable", status=402)
    return Allow(model=model, provider=provider, candidates=candidates, profile=snap.profile_index[provider.provider_id])
