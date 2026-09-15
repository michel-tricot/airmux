from __future__ import annotations

from dataclasses import replace

from contract.policies import AllowedModels
from data_plane.policy_actions.base import EvaluationState, ModelActionContext, blocked, evaluate_action


@evaluate_action.register(AllowedModels)
def evaluate(action: AllowedModels, context: ModelActionContext, state: EvaluationState) -> EvaluationState:
    return state if context.model.model_id in action.names else replace(state, denial=blocked(context.policy))
