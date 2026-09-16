from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from contract.policies import AllowedModels, AllowedProviders, CredentialAccess, DenyRequest, PriceLimit
from data_plane.credentials import policy_candidates, preferred_candidates
from data_plane.policies import matching_model_rules, matching_rules
from data_plane.policy_actions import ActionContext, EvaluationState, ModelActionContext, evaluate_action
from data_plane.requirements import required_capabilities, required_input_modalities

if TYPE_CHECKING:
    from contract import CredentialEntry, KeyEntry, ModelEntry, ProviderEntry
    from contract.policies import Fallback
    from data_plane.bundle.holder import BundleSnapshot
    from data_plane.canonical import CanonicalRequest
    from data_plane.policies import CompiledRule
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
    rules: tuple[CompiledRule, ...]


def evaluate(req: CanonicalRequest, key: KeyEntry, snap: BundleSnapshot, rules: tuple[CompiledRule, ...] | None = None) -> Decision:
    return evaluate_policies(req, key, snap, rules).decision


def model_allowed(model: ModelEntry, key: KeyEntry, snap: BundleSnapshot) -> bool:
    provider = snap.provider_index[model.provider_id]
    state = EvaluationState(candidates=policy_candidates(snap.credential_index, key.workspace_id, key.org_id, provider.provider_id))
    for compiled in matching_model_rules(model.model_id, key, snap.policy_index):
        action = compiled.definition.action
        if not isinstance(action, (AllowedModels, AllowedProviders, CredentialAccess, DenyRequest, PriceLimit)):
            continue
        context = ModelActionContext(
            policy=compiled.policy,
            key=key,
            model=model,
            provider=provider,
            profile=snap.profile_index[provider.provider_id],
        )
        state = evaluate_action(action, context, state)
        if state.denial is not None:
            return False
    return bool(preferred_candidates(state.candidates, key.workspace_id, key.org_id))


def evaluate_policies(req: CanonicalRequest, key: KeyEntry, snap: BundleSnapshot, rules: tuple[CompiledRule, ...] | None = None) -> PolicyEvaluation:
    """Return eligible credentials and fallback; cooldown-aware selection belongs to the request executor."""
    rules = matching_rules(req, key, snap.policy_index) if rules is None else rules
    route = _route(req, key, snap)
    if isinstance(route, Deny):
        return PolicyEvaluation(route, None, rules)
    state = EvaluationState(candidates=route.candidates)
    for compiled in rules:
        context = ActionContext(
            policy=compiled.policy,
            request=req,
            key=key,
            model=route.model,
            provider=route.provider,
            profile=route.profile,
        )
        state = evaluate_action(compiled.definition.action, context, state)
        if state.denial is not None:
            return PolicyEvaluation(Deny(code="policy_denied", status=403, message=state.denial), state.fallback, rules)
    candidates = preferred_candidates(state.candidates, key.workspace_id, key.org_id)
    if not candidates:
        return PolicyEvaluation(Deny(code="credential_unavailable", status=402), state.fallback, rules)
    return PolicyEvaluation(replace(route, candidates=candidates), state.fallback, rules)


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
