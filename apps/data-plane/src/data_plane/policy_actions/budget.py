from __future__ import annotations

from contract.policies import Budget
from data_plane.policy_actions.base import EvaluationState, ModelActionContext, evaluate_action


@evaluate_action.register(Budget)
def evaluate(_action: Budget, _context: ModelActionContext, state: EvaluationState) -> EvaluationState:
    return state
