from __future__ import annotations

from dataclasses import dataclass
from functools import singledispatch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contract import CredentialEntry, KeyEntry, ModelEntry, ProviderEntry
    from contract.policies import Fallback, PolicyAction, PolicyEntry
    from data_plane.canonical import CanonicalRequest


@dataclass(frozen=True)
class ActionContext:
    policy: PolicyEntry
    request: CanonicalRequest
    key: KeyEntry
    model: ModelEntry
    provider: ProviderEntry


@dataclass(frozen=True)
class EvaluationState:
    candidates: tuple[CredentialEntry, ...]
    denial: str | None = None
    fallback: Fallback | None = None


@singledispatch
def evaluate_action(action: object, _context: ActionContext, _state: EvaluationState) -> EvaluationState:
    msg = f"No policy evaluator registered for {type(action).__name__}"
    raise ValueError(msg)


def require_evaluator(action: PolicyAction) -> None:
    if evaluate_action.dispatch(type(action)) is evaluate_action.dispatch(object):
        msg = f"No policy evaluator registered for {type(action).__name__}"
        raise ValueError(msg)


def blocked(policy: PolicyEntry) -> str:
    return f"Blocked by policy {policy.name} ({policy.id})"
