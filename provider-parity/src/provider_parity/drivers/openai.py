from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

import openai
from openai import OpenAI

from provider_parity.drivers.base import Connection, SDKDriver, is_gateway_auth_failure
from provider_parity.drivers.normalize import openai_chat, openai_responses
from provider_parity.models import Case, Observation, Tool, Transport

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from openai.types.chat import ChatCompletionMessageParam
    from openai.types.responses import ResponseInputParam
    from pydantic import JsonValue


def _tool(tool: Tool, responses: bool) -> dict[str, JsonValue]:
    definition: dict[str, JsonValue] = {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
    if tool.strict is not None:
        definition["strict"] = tool.strict
    return {"type": "function", **definition} if responses else {"type": "function", "function": definition}


def _tool_choice(choice: JsonValue, responses: bool) -> JsonValue:
    if not isinstance(choice, dict) or not isinstance(choice.get("name"), str):
        return choice
    name = str(choice["name"])
    return {"type": "function", "name": name} if responses else {"type": "function", "function": {"name": name}}


def _image_url(block: Mapping[str, object]) -> str:
    if isinstance(block.get("url"), str):
        return str(block["url"])
    media_type = block.get("media_type")
    data = block.get("data")
    if not isinstance(media_type, str) or not isinstance(data, str):
        message = "an image block needs url or media_type and data"
        raise TypeError(message)
    return f"data:{media_type};base64,{data}"


def _messages(case: Case, responses: bool) -> list[dict[str, JsonValue]]:
    messages: list[dict[str, JsonValue]] = []
    for message in case.request.messages:
        content = message.get("content")
        if not isinstance(content, list):
            messages.append(dict(message))
            continue
        blocks: list[JsonValue] = []
        for value in cast("Sequence[object]", content):
            block = cast("Mapping[str, object]", value) if isinstance(value, dict) else {}
            if block.get("type") == "text":
                blocks.append({"type": "input_text" if responses else "text", "text": str(block.get("text") or "")})
            elif block.get("type") == "image":
                url = _image_url(block)
                blocks.append(
                    {"type": "input_image", "image_url": url, "detail": "auto"} if responses else {"type": "image_url", "image_url": {"url": url}}
                )
            else:
                blocks.append(cast("JsonValue", value))
        messages.append({"role": cast("JsonValue", message.get("role")), "content": blocks})
    return messages


def _chat_body(case: Case) -> dict[str, JsonValue]:
    request = case.request
    reasoning = request.reasoning or {}
    return {
        "max_tokens": request.max_tokens,
        **({"temperature": request.temperature} if request.temperature is not None else {}),
        **({"top_p": request.top_p} if request.top_p is not None else {}),
        **({"stop": list(request.stop)} if request.stop is not None else {}),
        **({"seed": request.seed} if request.seed is not None else {}),
        **({"tools": [_tool(tool, False) for tool in request.tools]} if request.tools else {}),
        **({"tool_choice": _tool_choice(request.tool_choice, False)} if request.tool_choice is not None else {}),
        **({"parallel_tool_calls": request.parallel_tool_calls} if request.parallel_tool_calls is not None else {}),
        **({"response_format": request.response_format} if request.response_format is not None else {}),
        **({"reasoning_effort": reasoning["effort"]} if reasoning.get("effort") is not None else {}),
        **request.extra,
    }


def _responses_body(case: Case) -> dict[str, JsonValue]:
    request = case.request
    response_format = request.response_format
    if response_format is not None and response_format.get("type") == "json_schema":
        schema = cast("dict[str, JsonValue]", response_format.get("json_schema") or {})
        output_format: dict[str, JsonValue] = {"type": "json_schema", **schema}
    else:
        output_format = cast("dict[str, JsonValue]", response_format or {})
    return {
        "max_output_tokens": request.max_tokens,
        **({"temperature": request.temperature} if request.temperature is not None else {}),
        **({"top_p": request.top_p} if request.top_p is not None else {}),
        **({"tools": [_tool(tool, True) for tool in request.tools]} if request.tools else {}),
        **({"tool_choice": _tool_choice(request.tool_choice, True)} if request.tool_choice is not None else {}),
        **({"parallel_tool_calls": request.parallel_tool_calls} if request.parallel_tool_calls is not None else {}),
        **({"text": {"format": output_format}} if output_format else {}),
        **(
            {"reasoning": {name: value for name, value in request.reasoning.items() if name in {"effort", "summary"}}}
            if request.reasoning is not None
            else {}
        ),
        **request.extra,
    }


def _unsupported(error: openai.APIStatusError) -> bool:
    message = str(error).casefold()
    return error.status_code in {400, 404, 422} and any(term in message for term in ("unsupported", "not support", "does not accept"))


class OpenAIDriver(SDKDriver):
    id = "openai"
    endpoints = frozenset({"chat/completions", "responses"})

    def execute(self, connection: Connection, endpoint: str, model: str, case: Case, transport: Transport) -> Observation:
        client = OpenAI(base_url=connection.base_url, api_key=connection.api_key, default_headers=connection.headers)
        started = time.perf_counter()
        try:
            if endpoint == "responses":
                return self._responses(client, model, case, transport, started)
            if endpoint == "chat/completions":
                return self._chat(client, model, case, transport, started)
            message = f"OpenAI SDK does not support endpoint {endpoint}"
            raise ValueError(message)
        except openai.APIStatusError as error:
            elapsed = (time.perf_counter() - started) * 1000
            gateway_auth_failure = is_gateway_auth_failure(connection, error.status_code)
            return Observation(
                outcome="inconclusive" if gateway_auth_failure else "unsupported" if _unsupported(error) else "error",
                error_code="gateway_authentication" if gateway_auth_failure else str(getattr(error, "code", None) or error.status_code),
                error_message=str(error)[:500],
                duration_ms=elapsed,
                sdk_type=type(error).__name__,
            )
        except openai.APIConnectionError as error:
            return Observation(outcome="inconclusive", error_code="connection_error", error_message=str(error)[:500], sdk_type=type(error).__name__)
        except IndexError as error:
            elapsed = (time.perf_counter() - started) * 1000
            return Observation(
                outcome="error",
                error_code="sdk_protocol_error",
                error_message=str(error)[:500] or "OpenAI SDK could not fold the response stream",
                duration_ms=elapsed,
                sdk_type=type(error).__name__,
            )

    @staticmethod
    def _responses(client: OpenAI, model: str, case: Case, transport: Transport, started: float) -> Observation:
        response_input = cast("ResponseInputParam", _messages(case, True))
        body = _responses_body(case)
        if transport == "streamed":
            with client.responses.stream(model=model, input=response_input, extra_body=body) as stream:
                response = stream.get_final_response()
        else:
            response = client.responses.create(model=model, input=response_input, extra_body=body)
        elapsed = (time.perf_counter() - started) * 1000
        return openai_responses(cast("Mapping[str, object]", response.model_dump()), elapsed, type(response).__name__)

    @classmethod
    def _chat(cls, client: OpenAI, model: str, case: Case, transport: Transport, started: float) -> Observation:
        messages = cast("list[ChatCompletionMessageParam]", _messages(case, False))
        body = _chat_body(case)
        if transport == "buffered":
            completion = client.chat.completions.create(model=model, messages=messages, extra_body=body)
            elapsed = (time.perf_counter() - started) * 1000
            return openai_chat(cast("Mapping[str, object]", completion.model_dump()), elapsed, type(completion).__name__)
        stream = client.chat.completions.create(model=model, messages=messages, stream=True, stream_options={"include_usage": True}, extra_body=body)
        events = [cast("Mapping[str, object]", event.model_dump()) for event in stream]
        elapsed = (time.perf_counter() - started) * 1000
        return cls._chat_stream(events, elapsed)

    @staticmethod
    def _chat_stream(events: list[Mapping[str, object]], duration_ms: float) -> Observation:
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
            choice = cast("Mapping[str, object]", choices[0])
            finish_reason = str(choice.get("finish_reason") or finish_reason or "") or None
            delta = cast("Mapping[str, object]", choice.get("delta") or {})
            if isinstance(delta.get("content"), str):
                text += str(delta["content"])
            reasoning_present = reasoning_present or bool(delta.get("reasoning_content") or delta.get("reasoning"))
            for call_value in cast("list[object]", delta.get("tool_calls") or []):
                call = cast("Mapping[str, object]", call_value)
                index = int(cast("int", call.get("index") or 0))
                function = cast("Mapping[str, object]", call.get("function") or {})
                name, arguments = tool_fragments.get(index, ("", ""))
                tool_fragments[index] = (name + str(function.get("name") or ""), arguments + str(function.get("arguments") or ""))
        payload = {
            "choices": [
                {
                    "message": {
                        "content": text,
                        "tool_calls": [
                            {"function": {"name": name, "arguments": arguments}} for _, (name, arguments) in sorted(tool_fragments.items())
                        ],
                        "reasoning": "present" if reasoning_present else None,
                    },
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {} if not usage_present else {"streamed": True},
        }
        return openai_chat(payload, duration_ms, "Stream[ChatCompletionChunk]")
