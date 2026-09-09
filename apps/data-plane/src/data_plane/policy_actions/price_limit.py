from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from contract.policies import PriceLimit
from data_plane.policy_actions.base import ActionContext, EvaluationState, blocked, evaluate_action


@evaluate_action.register(PriceLimit)
def evaluate(action: PriceLimit, context: ActionContext, state: EvaluationState) -> EvaluationState:
    input_price = Decimal(str(context.model.input_price_per_mtok))
    output_price = Decimal(str(context.model.output_price_per_mtok))
    if input_price <= action.max_input_price_per_mtok and output_price <= action.max_output_price_per_mtok:
        return state
    return replace(state, denial=f"{blocked(context.policy)}: model price exceeds the configured limit")
