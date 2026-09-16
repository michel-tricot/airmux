from __future__ import annotations

from dataclasses import dataclass
from functools import singledispatch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contract import CredentialEntry, KeyEntry, ModelEntry, ProviderEntry
    from contract.policies import Fallback, PolicyAction, PolicyEntry
    from data_plane.canonical import CanonicalRequest
    from data_plane.profiles import CompiledProfile


@dataclass(frozen=True)
class ModelActionContext:
    policy: PolicyEntry
    key: KeyEntry
    model: ModelEntry
    provider: ProviderEntry
    profile: CompiledProfile


@dataclass(frozen=True)
class ActionContext(ModelActionContext):
    request: CanonicalRequest


@dataclass(frozen=True)
class EvaluationState:
    candidates: tuple[CredentialEntry, ...]
    denial: str | None = None
    fallback: Fallback | None = None
    policy_max_output_tokens: int | None = None


@singledispatch
def evaluate_action(action: object, _context: ModelActionContext, _state: EvaluationState) -> EvaluationState:
    msg = f"No policy evaluator registered for {type(action).__name__}"
    raise ValueError(msg)


def require_evaluator(action: PolicyAction) -> None:
    if evaluate_action.dispatch(type(action)) is evaluate_action.dispatch(object):
        msg = f"No policy evaluator registered for {type(action).__name__}"
        raise ValueError(msg)


def blocked(policy: PolicyEntry) -> str:
    return f"Blocked by policy {policy.name} ({policy.id})"
