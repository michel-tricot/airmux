from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.canonical import CanonicalAdjustment, CanonicalRequest

if TYPE_CHECKING:
    from contract import ModelEntry
    from data_plane.profiles import CompiledProfile

GATEWAY_HELD = frozenset({"n"})
MODEL_TUNING_PARAMS = ("temperature", "top_p", "stop", "seed", "reasoning_effort", "parallel_tool_calls")


def _value(request: CanonicalRequest, param: str) -> object:
    if param == "reasoning_effort":
        return request.reasoning.effort if request.reasoning is not None else None
    return getattr(request, param)


def _drop_reason(request: CanonicalRequest, model: ModelEntry, profile: CompiledProfile, param: str) -> str | None:
    if model.parameter_support.get(param) == "unsupported":
        return f"{model.model_id} does not support this parameter"
    if param in GATEWAY_HELD:
        return "the response carries one completion; a sampling fan-out cannot forward"
    source = profile.respelled.get(param)
    if source is not None and getattr(request, source, None) is not None:
        return f"collides with {source}, which this provider spells {param}"
    if profile.params_closed and param not in profile.accepted:
        return f"{profile.provider_id} accepts only its declared params"
    return None


def dropped_parameters(request: CanonicalRequest, model: ModelEntry, profile: CompiledProfile) -> tuple[str, ...]:
    tuning = (param for param in MODEL_TUNING_PARAMS if _value(request, param) is not None)
    return tuple(sorted(param for param in (*tuning, *request.extra) if _drop_reason(request, model, profile, param) is not None))


def _reconcile_output_limit(
    request: CanonicalRequest, model: ModelEntry, policy_max_output_tokens: int | None
) -> tuple[CanonicalRequest, CanonicalAdjustment | None]:
    caller = request.max_output_tokens
    ceilings = tuple(limit for limit in (policy_max_output_tokens, model.max_output_tokens) if limit is not None)
    effective = min((caller, *ceilings)) if caller is not None else min(ceilings, default=None)
    if effective == caller:
        return request, None
    source = (
        "policy_and_model"
        if policy_max_output_tokens == model.max_output_tokens == effective
        else "policy"
        if policy_max_output_tokens == effective
        else "model"
    )
    action = "defaulted" if caller is None else "clamped"
    detail = f"{source.replace('_', ' ')} caps output at {effective} tokens"
    adjustment = CanonicalAdjustment(param="max_output_tokens", action=action, detail=detail, source=source)
    return request.model_copy(update={"max_output_tokens": effective}), adjustment


def reconcile(
    request: CanonicalRequest,
    model: ModelEntry,
    profile: CompiledProfile,
    policy_max_output_tokens: int | None = None,
) -> tuple[CanonicalRequest, list[CanonicalAdjustment]]:
    unsupported = {
        param for param in MODEL_TUNING_PARAMS if model.parameter_support.get(param) == "unsupported" and _value(request, param) is not None
    }
    adjustments = [
        CanonicalAdjustment(param=param, action="dropped", detail=f"{model.model_id} does not support this parameter") for param in unsupported
    ]
    if unsupported:
        updates = {param: None for param in unsupported if param != "reasoning_effort"}
        if "reasoning_effort" in unsupported and request.reasoning is not None:
            reasoning = request.reasoning.model_copy(update={"effort": None})
            updates["reasoning"] = reasoning if any(getattr(reasoning, name) is not None for name in reasoning.model_fields) else None
        request = request.model_copy(update=updates)
    forwarded: dict[str, object] = {}
    extra = request.extra
    for param, value in extra.items():
        reason = _drop_reason(request, model, profile, param)
        if reason is None:
            forwarded[param] = value
        else:
            adjustments.append(CanonicalAdjustment(param=param, action="dropped", detail=reason))
    request, limit_adjustment = _reconcile_output_limit(request, model, policy_max_output_tokens)
    if limit_adjustment is not None:
        adjustments.append(limit_adjustment)
    if len(forwarded) == len(extra):
        return request, adjustments
    core = {name: getattr(request, name) for name in CanonicalRequest.model_fields}
    return CanonicalRequest.model_validate({**forwarded, **core}), adjustments
