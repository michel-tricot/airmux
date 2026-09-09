from __future__ import annotations

from dataclasses import replace

from contract.policies import DenyRequest
from data_plane.policy_actions.base import ActionContext, EvaluationState, evaluate_action


@evaluate_action.register(DenyRequest)
def evaluate(action: DenyRequest, _context: ActionContext, state: EvaluationState) -> EvaluationState:
    return replace(state, denial=action.message)
