from __future__ import annotations

from dataclasses import replace

from contract.policies import AllowedProviders
from data_plane.policy_actions.base import EvaluationState, ModelActionContext, blocked, evaluate_action


@evaluate_action.register(AllowedProviders)
def evaluate(action: AllowedProviders, context: ModelActionContext, state: EvaluationState) -> EvaluationState:
    return state if context.provider.provider_id in action.names else replace(state, denial=blocked(context.policy))
