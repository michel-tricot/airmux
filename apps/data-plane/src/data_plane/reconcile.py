from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.canonical import Adjustment, CanonicalRequest

if TYPE_CHECKING:
    from contract import ModelEntry
    from data_plane.profiles import CompiledProfile

GATEWAY_HELD = frozenset({"n"})


def _drop_reason(request: CanonicalRequest, profile: CompiledProfile, param: str) -> str | None:
    if param in GATEWAY_HELD:
        return "the response carries one completion; a sampling fan-out cannot forward"
    source = profile.respelled.get(param)
    if source is not None and getattr(request, source, None) is not None:
        return f"collides with {source}, which this provider spells {param}"
    if profile.params_closed and param not in profile.accepted:
        return f"{profile.provider_id} accepts only its declared params"
    return None


def reconcile(request: CanonicalRequest, model: ModelEntry, profile: CompiledProfile) -> tuple[CanonicalRequest, list[Adjustment]]:
    adjustments = []
    forwarded: dict[str, object] = {}
    extra = request.extra
    for param, value in extra.items():
        reason = _drop_reason(request, profile, param)
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
