from __future__ import annotations

from dataclasses import replace

from contract.policies import PriceLimit
from data_plane.policy_actions.base import EvaluationState, ModelActionContext, blocked, evaluate_action


@evaluate_action.register(PriceLimit)
def evaluate(action: PriceLimit, context: ModelActionContext, state: EvaluationState) -> EvaluationState:
    if (
        context.model.input_price_per_mtok <= action.max_input_price_per_mtok
        and context.model.output_price_per_mtok <= action.max_output_price_per_mtok
    ):
        return state
    return replace(state, denial=f"{blocked(context.policy)}: model price exceeds the configured limit")
