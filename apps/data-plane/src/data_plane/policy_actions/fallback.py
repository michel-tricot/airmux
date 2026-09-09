from __future__ import annotations

from dataclasses import replace

from contract.policies import Fallback
from data_plane.policy_actions.base import ActionContext, EvaluationState, evaluate_action


@evaluate_action.register(Fallback)
def evaluate(action: Fallback, _context: ActionContext, state: EvaluationState) -> EvaluationState:
    return state if state.fallback is not None else replace(state, fallback=action)
