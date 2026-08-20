from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, cast

from provider_parity.models import Observation, ToolObservation

if TYPE_CHECKING:
    from pydantic import JsonValue


def _mapping(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    return cast("Sequence[object]", value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _adjustments(payload: Mapping[str, object]) -> tuple[str, ...]:
    gateway = _mapping(payload.get("gateway"))
    return tuple(
        f"{adjustment.get('param')}:{adjustment.get('action')}"
        for item in _sequence(gateway.get("adjustments"))
        if (adjustment := _mapping(item)).get("param") and adjustment.get("action")
    )


def _json_value(text: str) -> JsonValue | None:
    try:
        return cast("JsonValue", json.loads(text))
    except json.JSONDecodeError:
        return None


def openai_chat(payload: Mapping[str, object], duration_ms: float, sdk_type: str) -> Observation:
    choices = _sequence(payload.get("choices"))
    choice = _mapping(choices[0]) if choices else {}
    message = _mapping(choice.get("message"))
    content = message.get("content")
    text = content if isinstance(content, str) else ""
    calls = tuple(
        ToolObservation(name=str(function.get("name") or ""), arguments=str(function.get("arguments") or ""))
        for item in _sequence(message.get("tool_calls"))
        if (function := _mapping(_mapping(item).get("function"))).get("name")
    )
    reasoning = message.get("reasoning_content") or message.get("reasoning")
    return Observation(
        outcome="success",
        text=text,
        tool_calls=calls,
        finish_reason=str(choice["finish_reason"]) if choice.get("finish_reason") is not None else None,
        usage_present=bool(payload.get("usage")),
        reasoning_present=bool(reasoning),
        json_value=_json_value(text),
        adjustments=_adjustments(payload),
        duration_ms=duration_ms,
        sdk_type=sdk_type,
    )


def openai_responses(payload: Mapping[str, object], duration_ms: float, sdk_type: str) -> Observation:
    output = [_mapping(item) for item in _sequence(payload.get("output"))]
    calls = tuple(
        ToolObservation(name=str(item.get("name") or ""), arguments=str(item.get("arguments") or ""))
        for item in output
        if item.get("type") == "function_call"
    )
    text = "".join(
        str(part.get("text") or "")
        for item in output
        if item.get("type") == "message"
        for content in [_sequence(item.get("content"))]
        for value in content
        if (part := _mapping(value)).get("type") in {"output_text", "text"}
    )
    reasoning = any(item.get("type") == "reasoning" for item in output)
    return Observation(
        outcome="success",
        text=text,
        tool_calls=calls,
        finish_reason=str(payload.get("status") or "stop"),
        usage_present=bool(payload.get("usage")),
        reasoning_present=reasoning,
        json_value=_json_value(text),
        adjustments=_adjustments(payload),
        duration_ms=duration_ms,
        sdk_type=sdk_type,
    )


def anthropic_message(payload: Mapping[str, object], duration_ms: float, sdk_type: str) -> Observation:
    content = [_mapping(item) for item in _sequence(payload.get("content"))]
    text = "".join(str(item.get("text") or "") for item in content if item.get("type") == "text")
    calls = tuple(
        ToolObservation(name=str(item.get("name") or ""), arguments=json.dumps(item.get("input") or {}, separators=(",", ":")))
        for item in content
        if item.get("type") == "tool_use"
    )
    reasoning = any(item.get("type") in {"thinking", "redacted_thinking"} for item in content)
    return Observation(
        outcome="success",
        text=text,
        tool_calls=calls,
        finish_reason=str(payload["stop_reason"]) if payload.get("stop_reason") is not None else None,
        usage_present=bool(payload.get("usage")),
        reasoning_present=reasoning,
        json_value=_json_value(text),
        adjustments=_adjustments(payload),
        duration_ms=duration_ms,
        sdk_type=sdk_type,
    )
