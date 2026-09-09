from __future__ import annotations

from dataclasses import replace

from contract.policies import AllowedProviders
from data_plane.policy_actions.base import ActionContext, EvaluationState, blocked, evaluate_action


@evaluate_action.register(AllowedProviders)
def evaluate(action: AllowedProviders, context: ActionContext, state: EvaluationState) -> EvaluationState:
    return state if context.provider.provider_id in action.names else replace(state, denial=blocked(context.policy))
