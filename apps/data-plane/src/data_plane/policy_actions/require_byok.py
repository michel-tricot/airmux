from __future__ import annotations

from dataclasses import replace

from contract.policies import RequireByok
from data_plane.policy_actions.base import ActionContext, EvaluationState, blocked, evaluate_action


@evaluate_action.register(RequireByok)
def evaluate(_action: RequireByok, context: ActionContext, state: EvaluationState) -> EvaluationState:
    candidates = tuple(candidate for candidate in state.candidates if candidate.ref.org_id == context.key.org_id)
    return replace(state, candidates=candidates, denial=None if candidates else blocked(context.policy))
