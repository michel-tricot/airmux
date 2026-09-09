from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from contract.policies import Fallback, FallbackReason
from data_plane.policies import matching_policies
from data_plane.policy import Allow, Deny, evaluate

if TYPE_CHECKING:
    from contract import KeyEntry
    from data_plane.bundle.holder import BundleSnapshot
    from data_plane.canonical import CanonicalRequest


@dataclass(frozen=True)
class RoutePlan:
    primary: Allow
    backups: tuple[Allow, ...]
    retry_on: tuple[FallbackReason, ...]
    max_attempts: int
    timeout_ms: int | None


def plan_routes(request: CanonicalRequest, key: KeyEntry, snapshot: BundleSnapshot) -> RoutePlan | Deny:
    try:
        policies = matching_policies(request, key, snapshot.policy_index)
    except (ValueError, RuntimeError):
        return Deny(code="policy_error", status=403, message="A policy condition could not be evaluated")
    primary = evaluate(request, key, snapshot, policies)
    if isinstance(primary, Deny):
        return primary
    fallback = next((policy.definition.action for policy in policies if isinstance(policy.definition.action, Fallback)), None)
    if fallback is None:
        return RoutePlan(primary, (), (), len(primary.candidates), None)
    decisions = (
        evaluate(request.model_copy(update={"model": model}), key, snapshot, policies) for model in fallback.models if model != request.model
    )
    backups = tuple(decision for decision in decisions if isinstance(decision, Allow))
    return RoutePlan(primary, backups, fallback.on, fallback.max_attempts, fallback.timeout_ms)
