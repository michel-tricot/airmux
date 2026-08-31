from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic import JsonValue

    from model_audit.models import Case, Tool, Transport


def _openai_tool(tool: Tool, responses: bool) -> dict[str, JsonValue]:
    definition: dict[str, JsonValue] = {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
    if tool.strict is not None:
        definition["strict"] = tool.strict
    return {"type": "function", **definition} if responses else {"type": "function", "function": definition}


def _openai_tool_choice(choice: JsonValue, responses: bool) -> JsonValue:
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


def openai_messages(case: Case, responses: bool) -> list[dict[str, JsonValue]]:  # noqa: PLR0912 explicit canonical block variants
    messages: list[dict[str, JsonValue]] = []
    for message in case.request.messages:
        content = message.get("content")
        if not isinstance(content, list):
            messages.append(dict(message))
            continue
        if len(content) == 1 and isinstance(content[0], dict) and content[0].get("type") == "tool_call":
            block = cast("Mapping[str, object]", content[0])
            arguments = block.get("arguments")
            serialized = arguments if isinstance(arguments, str) else json.dumps(arguments or {}, separators=(",", ":"))
            if responses:
                messages.append(
                    {
                        "type": "function_call",
                        "call_id": cast("JsonValue", block.get("id")),
                        "name": cast("JsonValue", block.get("name")),
                        "arguments": serialized,
                    }
                )
            else:
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": cast("JsonValue", block.get("id")),
                                "type": "function",
                                "function": {"name": cast("JsonValue", block.get("name")), "arguments": serialized},
                            }
                        ],
                    }
                )
            continue
        if len(content) == 1 and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
            block = cast("Mapping[str, object]", content[0])
            if responses:
                messages.append(
                    {
                        "type": "function_call_output",
                        "call_id": cast("JsonValue", block.get("tool_call_id")),
                        "output": cast("JsonValue", block.get("content")),
                    }
                )
            else:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": cast("JsonValue", block.get("tool_call_id")),
                        "content": cast("JsonValue", block.get("content")),
                    }
                )
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
            elif block.get("type") == "document":
                media_type = str(block.get("media_type") or "application/pdf")
                data = str(block.get("data") or "")
                file_data = f"data:{media_type};base64,{data}"
                blocks.append(
                    {"type": "input_file", "filename": "audit.pdf", "file_data": file_data}
                    if responses
                    else {"type": "file", "file": {"filename": "audit.pdf", "file_data": file_data}}
                )
            else:
                blocks.append(cast("JsonValue", value))
        messages.append({"role": cast("JsonValue", message.get("role")), "content": blocks})
    return messages


def openai_chat_options(case: Case) -> dict[str, JsonValue]:
    request = case.request
    reasoning = request.reasoning or {}
    return {
        "max_tokens": case.max_output_tokens,
        **({"temperature": request.temperature} if request.temperature is not None else {}),
        **({"top_p": request.top_p} if request.top_p is not None else {}),
        **({"stop": list(request.stop)} if request.stop is not None else {}),
        **({"seed": request.seed} if request.seed is not None else {}),
        **({"logprobs": request.logprobs} if request.logprobs is not None else {}),
        **({"top_logprobs": request.top_logprobs} if request.top_logprobs is not None else {}),
        **({"tools": [_openai_tool(tool, False) for tool in request.tools]} if request.tools else {}),
        **({"tool_choice": _openai_tool_choice(request.tool_choice, False)} if request.tool_choice is not None else {}),
        **({"parallel_tool_calls": request.parallel_tool_calls} if request.parallel_tool_calls is not None else {}),
        **({"response_format": request.response_format} if request.response_format is not None else {}),
        **({"reasoning_effort": reasoning["effort"]} if reasoning.get("effort") is not None else {}),
    }


def openai_chat_body(model: str, case: Case, transport: Transport) -> dict[str, JsonValue]:
    streamed = transport == "streamed"
    return {
        "model": model,
        "messages": openai_messages(case, False),
        **openai_chat_options(case),
        **({"stream": True, "stream_options": {"include_usage": True}} if streamed else {}),
    }


def openai_responses_options(case: Case) -> dict[str, JsonValue]:
    request = case.request
    response_format = request.response_format
    if response_format is not None and response_format.get("type") == "json_schema":
        schema = cast("dict[str, JsonValue]", response_format.get("json_schema") or {})
        output_format: dict[str, JsonValue] = {"type": "json_schema", **schema}
    else:
        output_format = cast("dict[str, JsonValue]", response_format or {})
    return {
        "max_output_tokens": case.max_output_tokens,
        **({"temperature": request.temperature} if request.temperature is not None else {}),
        **({"top_p": request.top_p} if request.top_p is not None else {}),
        **({"tools": [_openai_tool(tool, True) for tool in request.tools]} if request.tools else {}),
        **({"tool_choice": _openai_tool_choice(request.tool_choice, True)} if request.tool_choice is not None else {}),
        **({"parallel_tool_calls": request.parallel_tool_calls} if request.parallel_tool_calls is not None else {}),
        **({"text": {"format": output_format}} if output_format else {}),
        **(
            {"reasoning": {name: value for name, value in request.reasoning.items() if name in {"effort", "summary"}}}
            if request.reasoning is not None
            else {}
        ),
    }


def openai_responses_body(model: str, case: Case, transport: Transport) -> dict[str, JsonValue]:
    return {
        "model": model,
        "input": openai_messages(case, True),
        **openai_responses_options(case),
        **({"store": False, "include": ["reasoning.encrypted_content"]} if case.request.reasoning is not None else {}),
        **({"stream": True} if transport == "streamed" else {}),
    }


def _anthropic_content(value: JsonValue) -> JsonValue:
    if not isinstance(value, list):
        return value
    content: list[JsonValue] = []
    for item in cast("Sequence[object]", value):
        block = cast("Mapping[str, object]", item) if isinstance(item, dict) else {}
        if block.get("type") == "text":
            content.append(
                {
                    "type": "text",
                    "text": str(block.get("text") or ""),
                    **({"cache_control": cast("JsonValue", block["cache_control"])} if block.get("cache_control") is not None else {}),
                }
            )
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
        elif block.get("type") == "document":
            content.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": str(block.get("media_type") or "application/pdf"),
                        "data": str(block.get("data") or ""),
                    },
                }
            )
        elif block.get("type") == "tool_call":
            content.append(
                {
                    "type": "tool_use",
                    "id": cast("JsonValue", block.get("id")),
                    "name": cast("JsonValue", block.get("name")),
                    "input": cast("JsonValue", block.get("arguments") or {}),
                }
            )
        elif block.get("type") == "tool_result":
            content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": cast("JsonValue", block.get("tool_call_id")),
                    "content": cast("JsonValue", block.get("content")),
                }
            )
        else:
            content.append(cast("JsonValue", item))
    return content


def anthropic_parts(case: Case) -> tuple[list[dict[str, JsonValue]], dict[str, JsonValue]]:
    request = case.request
    messages = [
        {"role": cast("JsonValue", message.get("role")), "content": _anthropic_content(cast("JsonValue", message.get("content")))}
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
    parallel = request.parallel_tool_calls
    if isinstance(choice, dict) and isinstance(choice.get("name"), str):
        tool_choice: JsonValue | None = {
            "type": "tool",
            "name": str(choice["name"]),
            **({"disable_parallel_tool_use": not parallel} if parallel is not None else {}),
        }
    elif choice == "required":
        tool_choice = {"type": "any", **({"disable_parallel_tool_use": not parallel} if parallel is not None else {})}
    elif isinstance(choice, str):
        tool_choice = {"type": choice, **({"disable_parallel_tool_use": not parallel} if parallel is not None else {})}
    else:
        tool_choice = None
    reasoning = request.reasoning or {}
    response_format = request.response_format or {}
    json_schema = cast("Mapping[str, object]", response_format.get("json_schema") or {})
    if response_format.get("type") == "json_schema" and isinstance(json_schema.get("schema"), dict):
        output_format: JsonValue | None = {"type": "json_schema", "schema": cast("JsonValue", json_schema["schema"])}
    elif response_format.get("type") == "json_object":
        output_format = {"type": "json_schema", "schema": {"type": "object"}}
    else:
        output_format = None
    output_config: dict[str, JsonValue] = {
        **({"effort": reasoning["effort"]} if reasoning.get("effort") is not None else {}),
        **({"format": output_format} if output_format is not None else {}),
    }
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
        **({"output_config": output_config} if output_config else {}),
    }
    return messages, extra


def anthropic_body(model: str, case: Case, transport: Transport) -> dict[str, JsonValue]:
    messages, extra = anthropic_parts(case)
    return {
        "model": model,
        "max_tokens": case.max_output_tokens,
        "messages": messages,
        **extra,
        **({"stream": True} if transport == "streamed" else {}),
    }


def body_of(endpoint: str, model: str, case: Case, transport: Transport) -> dict[str, JsonValue]:
    if endpoint == "chat/completions":
        return openai_chat_body(model, case, transport)
    if endpoint == "responses":
        return openai_responses_body(model, case, transport)
    if endpoint == "messages":
        return anthropic_body(model, case, transport)
    message = f"raw HTTP client does not support endpoint {endpoint}"
    raise ValueError(message)
