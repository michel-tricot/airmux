from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

import anthropic
from anthropic import Anthropic

from provider_parity.drivers.base import Connection, SDKDriver, is_gateway_auth_failure
from provider_parity.drivers.normalize import anthropic_message
from provider_parity.models import Case, Observation, Transport

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from anthropic.types import MessageParam
    from pydantic import JsonValue


def _content(value: JsonValue) -> JsonValue:
    if not isinstance(value, list):
        return value
    content: list[JsonValue] = []
    for item in cast("Sequence[object]", value):
        block = cast("Mapping[str, object]", item) if isinstance(item, dict) else {}
        if block.get("type") == "text":
            content.append({"type": "text", "text": str(block.get("text") or "")})
        elif block.get("type") == "image" and isinstance(block.get("url"), str):
            content.append({"type": "image", "source": {"type": "url", "url": str(block["url"])}})
        elif block.get("type") == "image":
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": str(block.get("media_type") or ""),
                        "data": str(block.get("data") or ""),
                    },
                }
            )
        else:
            content.append(cast("JsonValue", item))
    return content


def _body(case: Case) -> tuple[list[dict[str, JsonValue]], dict[str, JsonValue]]:
    request = case.request
    messages = [
        {"role": cast("JsonValue", message.get("role")), "content": _content(cast("JsonValue", message.get("content")))}
        for message in request.messages
        if message.get("role") != "system"
    ]
    system = [message.get("content") for message in request.messages if message.get("role") == "system"]
    tools = [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.parameters,
            **({"strict": tool.strict} if tool.strict is not None else {}),
        }
        for tool in request.tools
    ]
    choice = request.tool_choice
    if isinstance(choice, dict) and isinstance(choice.get("name"), str):
        tool_choice: JsonValue | None = {"type": "tool", "name": str(choice["name"])}
    elif choice == "required":
        tool_choice = {"type": "any"}
    elif isinstance(choice, str):
        tool_choice = {"type": choice}
    else:
        tool_choice = None
    reasoning = request.reasoning or {}
    extra: dict[str, JsonValue] = {
        **({"system": system[0]} if system else {}),
        **({"temperature": request.temperature} if request.temperature is not None else {}),
        **({"top_p": request.top_p} if request.top_p is not None else {}),
        **({"stop_sequences": list(request.stop)} if request.stop is not None else {}),
        **({"tools": tools} if tools else {}),
        **({"tool_choice": tool_choice} if tool_choice is not None else {}),
        **(
            {"thinking": {name: value for name, value in reasoning.items() if name in {"type", "budget_tokens", "display"}}}
            if reasoning.get("type")
            else {}
        ),
        **({"output_config": {"effort": reasoning["effort"]}} if reasoning.get("effort") is not None else {}),
        **request.extra,
    }
    return messages, extra


def _unsupported(error: anthropic.APIStatusError) -> bool:
    message = str(error).casefold()
    return error.status_code in {400, 404, 422} and any(term in message for term in ("unsupported", "not support", "does not accept"))


class AnthropicDriver(SDKDriver):
    id = "anthropic"
    endpoints = frozenset({"messages"})

    def execute(self, connection: Connection, endpoint: str, model: str, case: Case, transport: Transport) -> Observation:
        if endpoint not in self.endpoints:
            message = f"anthropic SDK does not support endpoint {endpoint}"
            raise ValueError(message)
        if connection.auth == "bearer":
            client = Anthropic(base_url=connection.base_url, api_key="unused", auth_token=connection.api_key, default_headers=connection.headers)
        else:
            client = Anthropic(base_url=connection.base_url, api_key=connection.api_key, default_headers=connection.headers)
        messages, extra = _body(case)
        started = time.perf_counter()
        try:
            message_params = cast("list[MessageParam]", messages)
            if transport == "streamed":
                with client.messages.stream(model=model, max_tokens=case.request.max_tokens, messages=message_params, extra_body=extra) as stream:
                    message = stream.get_final_message()
            else:
                message = client.messages.create(model=model, max_tokens=case.request.max_tokens, messages=message_params, extra_body=extra)
            elapsed = (time.perf_counter() - started) * 1000
            return anthropic_message(cast("Mapping[str, object]", message.model_dump()), elapsed, type(message).__name__)
        except anthropic.APIStatusError as error:
            elapsed = (time.perf_counter() - started) * 1000
            gateway_auth_failure = is_gateway_auth_failure(connection, error.status_code)
            return Observation(
                outcome="inconclusive" if gateway_auth_failure else "unsupported" if _unsupported(error) else "error",
                error_code="gateway_authentication" if gateway_auth_failure else str(getattr(error, "code", None) or error.status_code),
                error_message=str(error)[:500],
                duration_ms=elapsed,
                sdk_type=type(error).__name__,
            )
        except anthropic.APIConnectionError as error:
            return Observation(outcome="inconclusive", error_code="connection_error", error_message=str(error)[:500], sdk_type=type(error).__name__)
