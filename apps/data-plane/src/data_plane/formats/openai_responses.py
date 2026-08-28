"""OpenAI Responses JSON spelling shared by its ingress and egress adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from data_plane.canonical import (
    AssistantPart,
    CanonicalMessage,
    CanonicalRequest,
    DocumentPart,
    FinishReason,
    ImagePart,
    NamedTool,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolDef,
    ToolResultPart,
    Usage,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def _image(part: ImagePart) -> dict[str, str]:
    if part.url is not None:
        return {"type": "input_image", "image_url": part.url, "detail": "auto"}
    return {"type": "input_image", "image_url": f"data:{part.media_type};base64,{part.data}", "detail": "auto"}


def _document(part: DocumentPart) -> dict[str, str]:
    item = {"type": "input_file"}
    if part.filename is not None:
        item["filename"] = part.filename
    if part.file_id is not None:
        item["file_id"] = part.file_id
    elif part.data is not None:
        item["filename"] = part.filename or "document.pdf"
        item["file_data"] = f"data:{part.media_type};base64,{part.data}"
    else:
        item["file_url"] = part.url or ""
    return item


def input_of(messages: Sequence[CanonicalMessage]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        parts = list(message.content)
        results = [part for part in parts if isinstance(part, ToolResultPart)]
        items.extend(
            {
                "type": "function_call_output",
                "call_id": result.call_id,
                "output": "".join(part.text for part in result.content if isinstance(part, TextPart)),
            }
            for result in results
        )
        rest = [part for part in parts if not isinstance(part, ToolResultPart)]
        calls = [part for part in rest if isinstance(part, ToolCallPart)]
        items.extend({"type": "function_call", "call_id": call.id, "name": call.name, "arguments": call.arguments} for call in calls)
        reasoning = [part for part in rest if isinstance(part, ReasoningPart)]
        for part in reasoning:
            if part.id is None:
                error_message = "unsupported_feature: Responses reasoning history requires its original item id"
                raise ValueError(error_message)
            item: dict[str, Any] = {"type": "reasoning", "id": part.id, "summary": []}
            if part.signature:
                item["encrypted_content"] = part.signature
            items.append(item)
        if message.role == "assistant":
            said = "".join(part.text for part in rest if isinstance(part, TextPart))
            if said:
                items.append({"type": "message", "role": message.role, "content": said})
            continue
        content: list[dict[str, str]] = []
        for part in rest:
            if isinstance(part, TextPart):
                content.append({"type": "input_text", "text": part.text})
            elif isinstance(part, ImagePart):
                content.append(_image(part))
            elif isinstance(part, DocumentPart):
                content.append(_document(part))
        if content:
            items.append({"type": "message", "role": message.role, "content": content})
    return items


def tools_of(tools: Sequence[ToolDef] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "name": tool.name,
            **({"description": tool.description} if tool.description else {}),
            "parameters": tool.parameters,
            "strict": tool.strict,
        }
        for tool in tools
    ]


def tool_choice_of(choice: object) -> object:
    if isinstance(choice, NamedTool):
        return {"type": "function", "name": choice.name}
    return choice


def _reasoning_of(request: CanonicalRequest) -> dict[str, str] | None:
    if request.reasoning is None:
        return None
    reasoning = {name: value for name in ("effort", "summary") if (value := getattr(request.reasoning, name)) is not None}
    return reasoning or None


def body_of(request: CanonicalRequest, upstream_model: str) -> dict[str, Any]:
    unsupported = [name for name, value in (("stop", request.stop), ("seed", request.seed), *request.extra.items()) if value is not None]
    if unsupported:
        message = f"unsupported_feature: {', '.join(unsupported)} are not representable by Responses"
        raise ValueError(message)
    body: dict[str, Any] = {
        "model": upstream_model,
        "input": input_of(request.messages),
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    if request.stream:
        body["stream"] = True
    if request.max_tokens is not None:
        body["max_output_tokens"] = request.max_tokens
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.top_p is not None:
        body["top_p"] = request.top_p
    if tools := tools_of(request.tools):
        body["tools"] = tools
    if request.tool_choice is not None:
        body["tool_choice"] = tool_choice_of(request.tool_choice)
    if request.parallel_tool_calls is not None:
        body["parallel_tool_calls"] = request.parallel_tool_calls
    if reasoning := _reasoning_of(request):
        body["reasoning"] = reasoning
    if request.response_format is not None:
        if request.response_format.type == "json_schema":
            json_schema = dict(request.response_format.json_schema or {})
            json_schema.setdefault("name", "response")
            body["text"] = {"format": {"type": "json_schema", **json_schema}}
        elif request.response_format.type == "json_object":
            body["text"] = {"format": {"type": "json_object"}}
    return body


def _mapping(value: object) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


def _items(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def messages_of(value: object) -> list[CanonicalMessage]:  # noqa: PLR0912 - each supported item spelling maps explicitly
    raw_items = [_mapping(item) for item in value] if isinstance(value, list) else []
    messages: list[CanonicalMessage] = []
    pending_results: list[ToolResultPart] = []
    for item in raw_items:
        kind = item.get("type") or ("message" if "role" in item else None)
        if kind == "function_call_output":
            pending_results.append(ToolResultPart(call_id=_text(item.get("call_id")), content=[TextPart(text=_text(item.get("output")))]))
            continue
        if pending_results:
            messages.append(CanonicalMessage(role="user", content=pending_results))
            pending_results = []
        if kind == "function_call":
            messages.append(
                CanonicalMessage(
                    role="assistant",
                    content=[ToolCallPart(id=_text(item.get("call_id")), name=_text(item.get("name")), arguments=_text(item.get("arguments")))],
                )
            )
        elif kind == "reasoning":
            messages.append(
                CanonicalMessage(
                    role="assistant",
                    content=[
                        ReasoningPart(
                            id=_text(item.get("id")) or None,
                            text="",
                            signature=_text(item.get("encrypted_content")) or None,
                        )
                    ],
                )
            )
        elif kind == "message":
            role = item.get("role")
            canonical_role = "system" if role in {"system", "developer"} else role if role in {"user", "assistant"} else "user"
            raw_content = item.get("content")
            if isinstance(raw_content, str):
                if raw_content:
                    messages.append(CanonicalMessage(role=canonical_role, content=[TextPart(text=raw_content)]))
                continue
            parts = []
            for content in _items(raw_content):
                block = _mapping(content)
                if block.get("type") in {"input_text", "output_text", "text"}:
                    parts.append(TextPart(text=_text(block.get("text"))))
                elif block.get("type") == "input_image":
                    url = _text(block.get("image_url"))
                    if url.startswith("data:") and "," in url:
                        header, payload = url[5:].split(",", 1)
                        parts.append(ImagePart(data=payload, media_type=header.removesuffix(";base64")))
                    elif url:
                        parts.append(ImagePart(url=url))
                elif block.get("type") == "input_file":
                    filename = _text(block.get("filename")) or None
                    if file_id := _text(block.get("file_id")):
                        parts.append(DocumentPart(filename=filename, file_id=file_id))
                    elif file_data := _text(block.get("file_data")):
                        header, payload = file_data[5:].split(",", 1)
                        parts.append(DocumentPart(filename=filename, media_type=header.removesuffix(";base64"), data=payload))
                    elif file_url := _text(block.get("file_url")):
                        parts.append(DocumentPart(filename=filename, url=file_url))
            if parts:
                messages.append(CanonicalMessage(role=canonical_role, content=parts))
    if pending_results:
        messages.append(CanonicalMessage(role="user", content=pending_results))
    return messages


def response_parts(response: dict[str, Any]) -> list[AssistantPart]:
    parts: list[AssistantPart] = []
    for raw_item in _items(response.get("output")):
        item = _mapping(raw_item)
        if item.get("type") == "message":
            for raw_block in _items(item.get("content")):
                block = _mapping(raw_block)
                if block.get("type") == "output_text":
                    parts.append(TextPart(text=_text(block.get("text"))))
        elif item.get("type") == "reasoning":
            text = "".join(_text(_mapping(summary).get("text")) for summary in _items(item.get("summary")))
            parts.append(
                ReasoningPart(
                    id=_text(item.get("id")) or None,
                    text=text,
                    signature=_text(item.get("encrypted_content")) or None,
                )
            )
        elif item.get("type") == "function_call":
            parts.append(ToolCallPart(id=_text(item.get("call_id")), name=_text(item.get("name")), arguments=_text(item.get("arguments"))))
    return parts


def usage_of(value: object) -> Usage:
    usage = _mapping(value)
    input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return Usage(estimated=True)
    details = _mapping(usage.get("input_tokens_details"))
    cached = details.get("cached_tokens")
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens, cache_read_tokens=cached if isinstance(cached, int) else 0)


def finish_reason(response: dict[str, Any], parts: Sequence[AssistantPart]) -> FinishReason:
    if response.get("status") == "incomplete":
        reason = _mapping(response.get("incomplete_details")).get("reason")
        return "content_filter" if reason == "content_filter" else "length"
    return "tool_calls" if any(isinstance(part, ToolCallPart) for part in parts) else "stop"


def json_response(final_id: str, model: str, parts: Sequence[AssistantPart], finish: str | None, usage: Usage) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    for index, part in enumerate(parts):
        if isinstance(part, TextPart):
            output.append(
                {
                    "type": "message",
                    "id": f"msg_{index}",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": part.text, "annotations": []}],
                }
            )
        elif isinstance(part, ReasoningPart):
            output.append(
                {
                    "type": "reasoning",
                    "id": part.id or f"rs_{index}",
                    "summary": ([{"type": "summary_text", "text": part.text}] if part.text else []),
                    **({"encrypted_content": part.signature} if part.signature else {}),
                }
            )
        else:
            output.append(
                {
                    "type": "function_call",
                    "id": f"fc_{index}",
                    "call_id": part.id,
                    "name": part.name,
                    "arguments": part.arguments,
                    "status": "completed",
                }
            )
    incomplete_reason = {"length": "max_output_tokens", "content_filter": "content_filter"}.get(finish or "")
    return {
        "id": final_id,
        "object": "response",
        "status": "incomplete" if incomplete_reason else "completed",
        **({"incomplete_details": {"reason": incomplete_reason}} if incomplete_reason else {}),
        "model": model,
        "output": output,
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.input_tokens + usage.output_tokens,
            "input_tokens_details": {"cached_tokens": usage.cache_read_tokens},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }
