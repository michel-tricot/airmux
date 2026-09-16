from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from contract.policies import CredentialAccess
from data_plane.policy_actions.base import EvaluationState, ModelActionContext, blocked, evaluate_action

if TYPE_CHECKING:
    from contract import CredentialEntry, CredentialScope


@evaluate_action.register(CredentialAccess)
def evaluate(action: CredentialAccess, context: ModelActionContext, state: EvaluationState) -> EvaluationState:
    scopes = set(action.scopes)
    candidates = tuple(candidate for candidate in state.candidates if _scope(candidate) in scopes)
    return replace(state, candidates=candidates, denial=None if candidates else blocked(context.policy))


def _scope(candidate: CredentialEntry) -> CredentialScope:
    if candidate.ref.org_id is None:
        return "platform"
    return "workspace" if candidate.ref.workspace_id is not None else "org"
