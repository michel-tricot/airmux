from __future__ import annotations

from dataclasses import replace

from contract.policies import RequestLimits
from data_plane.policy_actions.base import ActionContext, EvaluationState, blocked, evaluate_action


@evaluate_action.register(RequestLimits)
def evaluate(action: RequestLimits, context: ActionContext, state: EvaluationState) -> EvaluationState:
    if context.request.max_output_tokens is not None and context.request.max_output_tokens > action.max_output_tokens:
        return replace(state, denial=f"{blocked(context.policy)}: requested output exceeds {action.max_output_tokens} tokens")
    ceiling = min(filter(None, (state.policy_max_output_tokens, action.max_output_tokens)))
    return replace(state, policy_max_output_tokens=ceiling)
