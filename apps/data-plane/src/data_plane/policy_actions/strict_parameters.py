from __future__ import annotations

from dataclasses import replace

from contract.policies import StrictParameters
from data_plane.policy_actions.base import ActionContext, EvaluationState, blocked, evaluate_action
from data_plane.reconcile import dropped_parameters


@evaluate_action.register(StrictParameters)
def evaluate(_action: StrictParameters, context: ActionContext, state: EvaluationState) -> EvaluationState:
    unsupported = dropped_parameters(context.request, context.model, context.profile)
    if not unsupported:
        return state
    return replace(state, denial=f"{blocked(context.policy)}: unsupported parameters: {', '.join(unsupported)}")
