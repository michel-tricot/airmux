from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, cast

from model_audit.models import Observation, ToolObservation

if TYPE_CHECKING:
    from pydantic import JsonValue

RESPONSES_TRANSIENT_CODES = frozenset({"rate_limit", "rate_limit_exceeded", "slow_down"})


def _mapping(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    return cast("Sequence[object]", value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _index(value: object) -> int:
    return value if isinstance(value, int) else 0


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


def openai_chat(payload: Mapping[str, object], duration_ms: float, client_type: str) -> Observation:
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
    reasoning_present = any(name in message and message[name] is not None for name in ("reasoning_content", "reasoning"))
    return Observation(
        outcome="success",
        text=text,
        tool_calls=calls,
        finish_reason=str(choice["finish_reason"]) if choice.get("finish_reason") is not None else None,
        usage_present=bool(payload.get("usage")),
        reasoning_present=reasoning_present,
        json_value=_json_value(text),
        adjustments=_adjustments(payload),
        duration_ms=duration_ms,
        client_type=client_type,
    )


def openai_responses(payload: Mapping[str, object], duration_ms: float, client_type: str) -> Observation:
    status = str(payload.get("status") or "completed")
    error = _mapping(payload.get("error"))
    if status == "failed":
        error_code = str(error.get("code") or "response_failed")
        return Observation(
            outcome="transient" if error_code in RESPONSES_TRANSIENT_CODES else "error",
            error_code=error_code,
            error_message=str(error.get("message") or "response generation failed"),
            finish_reason=status,
            usage_present=bool(payload.get("usage")),
            adjustments=_adjustments(payload),
            duration_ms=duration_ms,
            client_type=client_type,
        )
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
    incomplete = _mapping(payload.get("incomplete_details"))
    return Observation(
        outcome="success",
        text=text,
        tool_calls=calls,
        finish_reason=str(incomplete.get("reason") or ("tool_calls" if calls else status) or "stop"),
        usage_present=bool(payload.get("usage")),
        reasoning_present=reasoning,
        json_value=_json_value(text),
        adjustments=_adjustments(payload),
        duration_ms=duration_ms,
        client_type=client_type,
    )


def anthropic_message(payload: Mapping[str, object], duration_ms: float, client_type: str) -> Observation:
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
        client_type=client_type,
    )


def openai_chat_stream(events: Sequence[Mapping[str, object]], duration_ms: float, client_type: str) -> Observation:
    text = ""
    finish_reason = None
    usage_present = False
    tool_fragments: dict[int, tuple[str, str]] = {}
    reasoning_present = False
    for event in events:
        usage_present = usage_present or bool(event.get("usage"))
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        choice = _mapping(choices[0])
        finish_reason = str(choice.get("finish_reason") or finish_reason or "") or None
        delta = _mapping(choice.get("delta"))
        if isinstance(delta.get("content"), str):
            text += str(delta["content"])
        reasoning_present = reasoning_present or any(name in delta and delta[name] is not None for name in ("reasoning_content", "reasoning"))
        for call_value in _sequence(delta.get("tool_calls")):
            call = _mapping(call_value)
            index = _index(call.get("index"))
            function = _mapping(call.get("function"))
            name, arguments = tool_fragments.get(index, ("", ""))
            tool_fragments[index] = (name + str(function.get("name") or ""), arguments + str(function.get("arguments") or ""))
    payload = {
        "choices": [
            {
                "message": {
                    "content": text,
                    "tool_calls": [{"function": {"name": name, "arguments": arguments}} for _, (name, arguments) in sorted(tool_fragments.items())],
                    "reasoning": "present" if reasoning_present else None,
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {} if not usage_present else {"streamed": True},
    }
    return openai_chat(payload, duration_ms, client_type)


def openai_responses_stream(events: Sequence[Mapping[str, object]], duration_ms: float, client_type: str) -> Observation:
    for event in reversed(events):
        if event.get("type") in {"response.completed", "response.failed", "response.incomplete"}:
            return openai_responses(_mapping(event.get("response")), duration_ms, client_type)
        if event.get("type") == "error":
            payload = {"status": "failed", "error": event.get("error"), "gateway": event.get("gateway")}
            return openai_responses(payload, duration_ms, client_type)
    message = "Responses stream did not include a terminal response event"
    raise ValueError(message)


def anthropic_stream(events: Sequence[Mapping[str, object]], duration_ms: float, client_type: str) -> Observation:
    message: dict[str, object] = {}
    content: dict[int, dict[str, object]] = {}
    input_fragments: dict[int, str] = {}
    usage: dict[str, object] = {}
    for event in events:
        kind = event.get("type")
        if kind == "message_start":
            message.update(_mapping(event.get("message")))
            usage.update(_mapping(message.get("usage")))
        elif kind == "content_block_start":
            index = _index(event.get("index"))
            content[index] = dict(_mapping(event.get("content_block")))
        elif kind == "content_block_delta":
            index = _index(event.get("index"))
            block = content.setdefault(index, {})
            delta = _mapping(event.get("delta"))
            if delta.get("type") == "text_delta":
                block["text"] = str(block.get("text") or "") + str(delta.get("text") or "")
            elif delta.get("type") == "thinking_delta":
                block["thinking"] = str(block.get("thinking") or "") + str(delta.get("thinking") or "")
            elif delta.get("type") == "signature_delta":
                block["signature"] = str(block.get("signature") or "") + str(delta.get("signature") or "")
            elif delta.get("type") == "input_json_delta":
                input_fragments[index] = input_fragments.get(index, "") + str(delta.get("partial_json") or "")
        elif kind == "message_delta":
            delta = _mapping(event.get("delta"))
            if delta.get("stop_reason") is not None:
                message["stop_reason"] = delta["stop_reason"]
            usage.update(_mapping(event.get("usage")))
    for index, fragment in input_fragments.items():
        try:
            content[index]["input"] = json.loads(fragment)
        except json.JSONDecodeError:
            content[index]["input"] = fragment
    payload = {**message, "content": [block for _, block in sorted(content.items())], "usage": usage}
    return anthropic_message(payload, duration_ms, client_type)
