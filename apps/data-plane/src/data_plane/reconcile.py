from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.canonical import Adjustment, CanonicalRequest

if TYPE_CHECKING:
    from contract import ModelEntry
    from data_plane.profiles import CompiledProfile

GATEWAY_HELD = frozenset({"n"})
MODEL_TUNING_PARAMS = ("temperature", "top_p", "stop", "seed", "reasoning_effort", "parallel_tool_calls")


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


def reconcile(request: CanonicalRequest, model: ModelEntry, profile: CompiledProfile) -> tuple[CanonicalRequest, list[Adjustment]]:
    unsupported = {
        param: None for param in MODEL_TUNING_PARAMS if model.parameter_support.get(param) == "unsupported" and getattr(request, param) is not None
    }
    adjustments = [Adjustment(param=param, action="dropped", detail=f"{model.model_id} does not support this parameter") for param in unsupported]
    if unsupported:
        request = request.model_copy(update=unsupported)
    forwarded: dict[str, object] = {}
    extra = request.extra
    for param, value in extra.items():
        reason = _drop_reason(request, model, profile, param)
        if reason is None:
            forwarded[param] = value
        else:
            adjustments.append(Adjustment(param=param, action="dropped", detail=reason))
    if request.max_tokens and model.max_output_tokens and request.max_tokens > model.max_output_tokens:
        adjustments.append(Adjustment(param="max_tokens", action="clamped", detail=f"model caps output at {model.max_output_tokens} tokens"))
        request = request.model_copy(update={"max_tokens": model.max_output_tokens})
    if len(forwarded) == len(extra):
        return request, adjustments
    core = {name: getattr(request, name) for name in CanonicalRequest.model_fields}
    return CanonicalRequest.model_validate({**forwarded, **core}), adjustments
