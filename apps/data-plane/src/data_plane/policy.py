from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from data_plane.credentials import policy_candidates, preferred_candidates
from data_plane.policies import matching_policies
from data_plane.policy_actions import ActionContext, EvaluationState, evaluate_action
from data_plane.requirements import required_capabilities, required_input_modalities

if TYPE_CHECKING:
    from contract import CredentialEntry, KeyEntry, ModelEntry, ProviderEntry
    from contract.policies import Fallback, PolicyEntry
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
    code: Literal[
        "unknown_model",
        "unsupported_input_modality",
        "unsupported_feature",
        "provider_not_configured",
        "credential_unavailable",
        "policy_denied",
    ]
    status: int
    message: str = ""


type Decision = Allow | Deny


@dataclass(frozen=True)
class PolicyEvaluation:
    decision: Decision
    fallback: Fallback | None
    policies: tuple[PolicyEntry, ...]


def evaluate(req: CanonicalRequest, key: KeyEntry, snap: BundleSnapshot, policies: tuple[PolicyEntry, ...] | None = None) -> Decision:
    return evaluate_policies(req, key, snap, policies).decision


def evaluate_policies(
    req: CanonicalRequest, key: KeyEntry, snap: BundleSnapshot, policies: tuple[PolicyEntry, ...] | None = None
) -> PolicyEvaluation:
    """Return eligible credentials and fallback; cooldown-aware selection belongs to the request executor."""
    policies = matching_policies(req, key, snap.policy_index) if policies is None else policies
    route = _route(req, key, snap)
    if isinstance(route, Deny):
        return PolicyEvaluation(route, None, policies)
    state = EvaluationState(candidates=route.candidates)
    for policy in policies:
        context = ActionContext(policy=policy, request=req, key=key, model=route.model, provider=route.provider, profile=route.profile)
        state = evaluate_action(policy.definition.action, context, state)
        if state.denial is not None:
            return PolicyEvaluation(Deny(code="policy_denied", status=403, message=state.denial), state.fallback, policies)
    candidates = preferred_candidates(state.candidates, key.workspace_id, key.org_id)
    if not candidates:
        return PolicyEvaluation(Deny(code="credential_unavailable", status=402), state.fallback, policies)
    return PolicyEvaluation(replace(route, candidates=candidates), state.fallback, policies)


def _route(req: CanonicalRequest, key: KeyEntry, snap: BundleSnapshot) -> Decision:
    model = snap.model_index.get(req.model)
    if model is None:
        return Deny(code="unknown_model", status=404)
    missing_modalities = sorted(required_input_modalities(req) - set(model.input_modalities))
    if missing_modalities:
        return Deny(code="unsupported_input_modality", message=", ".join(missing_modalities), status=400)
    missing = sorted(required_capabilities(req) - set(model.capabilities))
    if missing:
        return Deny(code="unsupported_feature", message=", ".join(missing), status=400)
    provider = snap.provider_index.get(model.provider_id)
    if provider is None:
        return Deny(code="provider_not_configured", status=502)
    candidates = policy_candidates(snap.credential_index, key.workspace_id, key.org_id, provider.provider_id)
    return Allow(model=model, provider=provider, candidates=candidates, profile=snap.profile_index[provider.provider_id])
