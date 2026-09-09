from __future__ import annotations

from contract.policies import Budget
from data_plane.policy_actions.base import ActionContext, EvaluationState, evaluate_action


@evaluate_action.register(Budget)
def evaluate(_action: Budget, _context: ActionContext, state: EvaluationState) -> EvaluationState:
    # FIXME: Enforce budgets after spend reservation and multi-instance accounting semantics are defined
    return state
