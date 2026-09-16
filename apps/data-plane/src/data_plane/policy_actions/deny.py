from __future__ import annotations

from dataclasses import replace

from contract.policies import DenyRequest
from data_plane.policy_actions.base import EvaluationState, ModelActionContext, evaluate_action


@evaluate_action.register(DenyRequest)
def evaluate(action: DenyRequest, _context: ModelActionContext, state: EvaluationState) -> EvaluationState:
    return replace(state, denial=action.message)
