from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, cast

from model_audit.models import Observation, ReasoningObservation, ToolObservation, UsageObservation

if TYPE_CHECKING:
    from pydantic import JsonValue

RESPONSES_TRANSIENT_CODES = frozenset({"rate_limit", "rate_limit_exceeded", "slow_down"})


def _mapping(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    return cast("Sequence[object]", value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _index(value: object) -> int:
    return value if isinstance(value, int) else 0


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _first_integer(payload: Mapping[str, object], *names: str) -> int | None:
    return next((_integer(payload.get(name)) for name in names if _integer(payload.get(name)) is not None), None)


def _usage(payload: Mapping[str, object]) -> UsageObservation | None:
    raw = _mapping(payload.get("usage"))
    if not raw:
        return None
    input_tokens = _first_integer(raw, "input_tokens", "prompt_tokens")
    output_tokens = _first_integer(raw, "output_tokens", "completion_tokens")
    total_tokens = _integer(raw.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return UsageObservation(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens)


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


def _openai_content(value: object) -> tuple[str, bool]:
    if isinstance(value, str):
        return value, False
    blocks = [_mapping(item) for item in _sequence(value)]
    text = "".join(str(block.get("text") or "") for block in blocks if block.get("type") == "text")
    reasoning = any(block.get("type") == "thinking" for block in blocks)
    return text, reasoning


def openai_chat(payload: Mapping[str, object], duration_ms: float, client_type: str) -> Observation:
    choices = _sequence(payload.get("choices"))
    choice = _mapping(choices[0]) if choices else {}
    message = _mapping(choice.get("message"))
    text, content_reasoning = _openai_content(message.get("content"))
    calls = tuple(
        ToolObservation(
            id=str(call.get("id")) if call.get("id") is not None else None,
            name=str(function.get("name") or ""),
            arguments=str(function.get("arguments") or ""),
        )
        for item in _sequence(message.get("tool_calls"))
        if (call := _mapping(item)) and (function := _mapping(call.get("function"))).get("name")
    )
    reasoning_present = content_reasoning or any(name in message and message[name] is not None for name in ("reasoning_content", "reasoning"))
    usage = _usage(payload)
    return Observation(
        outcome="success",
        text=text,
        tool_calls=calls,
        finish_reason=str(choice["finish_reason"]) if choice.get("finish_reason") is not None else None,
        usage_present=usage is not None,
        reasoning_present=reasoning_present,
        usage=usage,
        reasoning=ReasoningObservation(exposed=True, kind="thinking" if content_reasoning else None) if reasoning_present else None,
        json_value=_json_value(text),
        adjustments=_adjustments(payload),
        duration_ms=duration_ms,
        client_type=client_type,
    )


def openai_responses(payload: Mapping[str, object], duration_ms: float, client_type: str) -> Observation:
    status = str(payload.get("status") or "completed")
    error = _mapping(payload.get("error"))
    usage = _usage(payload)
    if status == "failed":
        error_code = str(error.get("code") or "response_failed")
        return Observation(
            outcome="transient" if error_code in RESPONSES_TRANSIENT_CODES else "error",
            error_code=error_code,
            error_message=str(error.get("message") or "response generation failed"),
            finish_reason=status,
            usage_present=usage is not None,
            usage=usage,
            adjustments=_adjustments(payload),
            duration_ms=duration_ms,
            client_type=client_type,
        )
    output = [_mapping(item) for item in _sequence(payload.get("output"))]
    calls = tuple(
        ToolObservation(
            id=str(item.get("call_id")) if item.get("call_id") is not None else None,
            name=str(item.get("name") or ""),
            arguments=str(item.get("arguments") or ""),
        )
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
        usage_present=usage is not None,
        reasoning_present=reasoning,
        usage=usage,
        reasoning=ReasoningObservation(exposed=True, kind="reasoning") if reasoning else None,
        json_value=_json_value(text),
        adjustments=_adjustments(payload),
        duration_ms=duration_ms,
        client_type=client_type,
    )


def anthropic_message(payload: Mapping[str, object], duration_ms: float, client_type: str) -> Observation:
    content = [_mapping(item) for item in _sequence(payload.get("content"))]
    text = "".join(str(item.get("text") or "") for item in content if item.get("type") == "text")
    calls = tuple(
        ToolObservation(
            id=str(item.get("id")) if item.get("id") is not None else None,
            name=str(item.get("name") or ""),
            arguments=json.dumps(item.get("input") or {}, separators=(",", ":")),
        )
        for item in content
        if item.get("type") == "tool_use"
    )
    reasoning = any(item.get("type") in {"thinking", "redacted_thinking"} for item in content)
    signature_present = any(item.get("type") == "thinking" and item.get("signature") is not None for item in content)
    usage = _usage(payload)
    return Observation(
        outcome="success",
        text=text,
        tool_calls=calls,
        finish_reason=str(payload["stop_reason"]) if payload.get("stop_reason") is not None else None,
        usage_present=usage is not None,
        reasoning_present=reasoning,
        usage=usage,
        reasoning=ReasoningObservation(exposed=True, kind="thinking", signature_present=signature_present) if reasoning else None,
        json_value=_json_value(text),
        adjustments=_adjustments(payload),
        duration_ms=duration_ms,
        client_type=client_type,
    )


def openai_chat_stream(events: Sequence[Mapping[str, object]], duration_ms: float, client_type: str) -> Observation:
    text = ""
    finish_reason = None
    usage: Mapping[str, object] = {}
    tool_fragments: dict[int, tuple[str | None, str, str]] = {}
    reasoning_present = False
    for event in events:
        if event.get("usage"):
            usage = _mapping(event.get("usage"))
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        choice = _mapping(choices[0])
        finish_reason = str(choice.get("finish_reason") or finish_reason or "") or None
        delta = _mapping(choice.get("delta"))
        content_text, content_reasoning = _openai_content(delta.get("content"))
        text += content_text
        reasoning_present = (
            reasoning_present or content_reasoning or any(name in delta and delta[name] is not None for name in ("reasoning_content", "reasoning"))
        )
        for call_value in _sequence(delta.get("tool_calls")):
            call = _mapping(call_value)
            index = _index(call.get("index"))
            function = _mapping(call.get("function"))
            call_id, name, arguments = tool_fragments.get(index, (None, "", ""))
            tool_fragments[index] = (
                str(call.get("id")) if call.get("id") is not None else call_id,
                name + str(function.get("name") or ""),
                arguments + str(function.get("arguments") or ""),
            )
    payload = {
        "choices": [
            {
                "message": {
                    "content": text,
                    "tool_calls": [
                        {"id": call_id, "function": {"name": name, "arguments": arguments}}
                        for _, (call_id, name, arguments) in sorted(tool_fragments.items())
                    ],
                    "reasoning": "present" if reasoning_present else None,
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
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
