from __future__ import annotations

from dataclasses import replace

from contract.policies import AllowedModels
from data_plane.policy_actions.base import ActionContext, EvaluationState, blocked, evaluate_action


@evaluate_action.register(AllowedModels)
def evaluate(action: AllowedModels, context: ActionContext, state: EvaluationState) -> EvaluationState:
    return state if context.model.model_id in action.names else replace(state, denial=blocked(context.policy))
