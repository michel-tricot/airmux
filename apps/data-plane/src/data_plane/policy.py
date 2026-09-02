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


def required_capabilities(req: CanonicalRequest) -> frozenset[str]:
    part_capabilities = {"reasoning": "reasoning", "tool_call": "tools", "tool_result": "tools"}
    capabilities = {capability for message in req.messages for part in message.content if (capability := part_capabilities.get(part.type))}
    if req.stream:
        capabilities.add("streaming")
    if req.tools or req.tool_choice is not None:
        capabilities.add("tools")
    if req.reasoning is not None:
        capabilities.add("reasoning")
    if req.response_format is not None and req.response_format.type != "text":
        capabilities.add("structured_output")
    return frozenset(capabilities)


def required_input_modalities(req: CanonicalRequest) -> frozenset[str]:
    part_modalities = {"image": "image", "document": "pdf"}
    return frozenset(modality for message in req.messages for part in message.content if (modality := part_modalities.get(part.type)))


def evaluate(req: CanonicalRequest, key: KeyEntry, snap: BundleSnapshot) -> Decision:
    """Pure and synchronous: no async, no network, no I/O, no datetime.now(). Under 100 lines.

    Returns the credentials that may be spent rather than a choice between them: picking one means
    knowing which are in cooldown, which is state, and state does not belong in a pure function.
    """
    model = snap.model_index.get(req.model)
    if model is None:
        return Deny(reason="unknown_model", status=404)
    missing_modalities = sorted(required_input_modalities(req) - set(model.input_modalities))
    if missing_modalities:
        return Deny(reason=f"unsupported_input_modality: {', '.join(missing_modalities)}", status=400)
    missing = sorted(required_capabilities(req) - set(model.capabilities))
    if missing:
        return Deny(reason=f"unsupported_feature: {', '.join(missing)}", status=400)
    provider = snap.provider_index.get(model.provider_id)
    if provider is None:
        return Deny(reason="provider_not_configured", status=502)
    candidates = candidates_for(snap.credential_index, key.workspace_id, key.org_id, provider.provider_id)
    if not candidates:
        return Deny(reason="credential_unavailable", status=402)
    return Allow(model=model, provider=provider, candidates=candidates, profile=snap.profile_index[provider.provider_id])
