from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from data_plane.policy import Allow, Deny, evaluate, evaluate_policies

if TYPE_CHECKING:
    from contract import KeyEntry
    from contract.policies import FallbackReason
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
    evaluation = evaluate_policies(request, key, snapshot)
    primary = evaluation.decision
    if isinstance(primary, Deny):
        return primary
    fallback = evaluation.fallback
    if fallback is None:
        return RoutePlan(primary, (), (), len(primary.candidates), None)
    decisions = (
        evaluate(request.model_copy(update={"model": model}), key, snapshot, evaluation.policies)
        for model in fallback.models
        if model != request.model
    )
    backups = tuple(decision for decision in decisions if isinstance(decision, Allow))
    return RoutePlan(primary, backups, fallback.on, fallback.max_attempts, fallback.timeout_ms)
