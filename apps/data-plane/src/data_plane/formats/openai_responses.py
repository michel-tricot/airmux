"""OpenAI Responses JSON spelling shared by its ingress and egress adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, ConfigDict, Field

from data_plane.canonical import (
    CanonicalAssistantMessage,
    CanonicalAssistantPart,
    CanonicalDocumentPart,
    CanonicalFinishReason,
    CanonicalImagePart,
    CanonicalMessage,
    CanonicalNamedTool,
    CanonicalReasoningPart,
    CanonicalRequest,
    CanonicalSystemMessage,
    CanonicalTextPart,
    CanonicalToolCallPart,
    CanonicalToolDef,
    CanonicalToolResultPart,
    CanonicalUsage,
    CanonicalUserMessage,
)
from data_plane.errors import UnsupportedFeatureError

if TYPE_CHECKING:
    from collections.abc import Sequence


class UpstreamError(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    code: str | None = None
    message: str = ""


class UpstreamText(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str
    text: str = ""


class UpstreamTokenDetails(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    cached_tokens: int = Field(default=0, ge=0, strict=True)


class UpstreamUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    input_tokens_details: UpstreamTokenDetails | None = None


class UpstreamIncompleteDetails(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    reason: str


class UpstreamOutputItem(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    type: str = ""
    id: str = ""
    call_id: str = ""
    name: str = ""
    arguments: str = ""
    encrypted_content: str = ""
    content: list[UpstreamText] = Field(default_factory=list)
    summary: list[UpstreamText] = Field(default_factory=list)


class UpstreamResponse(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    id: str = ""
    status: str | None = None
    output: list[UpstreamOutputItem]
    usage: UpstreamUsage | None = None
    incomplete_details: UpstreamIncompleteDetails | None = None
    error: UpstreamError | None = None


class UpstreamResponseEvent(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    type: str | None = None
    response: UpstreamResponse | None = None
    error: UpstreamError | None = None
    output_index: int | None = None
    item: UpstreamOutputItem | None = None
    delta: str = ""


@dataclass(frozen=True)
class ResponseMetadata:
    id: str
    model: str
    created_at: int


def _image(part: CanonicalImagePart) -> dict[str, str]:
    if part.url is not None:
        return {"type": "input_image", "image_url": part.url, "detail": "auto"}
    return {"type": "input_image", "image_url": f"data:{part.media_type};base64,{part.data}", "detail": "auto"}


def _document(part: CanonicalDocumentPart) -> dict[str, str]:
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
        results = [part for part in parts if isinstance(part, CanonicalToolResultPart)]
        items.extend(
            {
                "type": "function_call_output",
                "call_id": result.call_id,
                "output": "".join(part.text for part in result.content if isinstance(part, CanonicalTextPart)),
            }
            for result in results
        )
        rest = [part for part in parts if not isinstance(part, CanonicalToolResultPart)]
        calls = [part for part in rest if isinstance(part, CanonicalToolCallPart)]
        items.extend({"type": "function_call", "call_id": call.id, "name": call.name, "arguments": call.arguments} for call in calls)
        reasoning = [part for part in rest if isinstance(part, CanonicalReasoningPart)]
        for part in reasoning:
            if part.id is None:
                error_message = "Responses reasoning history requires its original item id"
                raise UnsupportedFeatureError(error_message)
            item: dict[str, Any] = {"type": "reasoning", "id": part.id, "summary": []}
            if part.signature:
                item["encrypted_content"] = part.signature
            items.append(item)
        if message.role == "assistant":
            said = "".join(part.text for part in rest if isinstance(part, CanonicalTextPart))
            if said:
                items.append({"type": "message", "role": message.role, "content": said})
            continue
        content: list[dict[str, str]] = []
        for part in rest:
            if isinstance(part, CanonicalTextPart):
                content.append({"type": "input_text", "text": part.text})
            elif isinstance(part, CanonicalImagePart):
                content.append(_image(part))
            elif isinstance(part, CanonicalDocumentPart):
                content.append(_document(part))
        if content:
            items.append({"type": "message", "role": message.role, "content": content})
    return items


def tools_of(tools: Sequence[CanonicalToolDef] | None) -> list[dict[str, Any]] | None:
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
    if isinstance(choice, CanonicalNamedTool):
        return {"type": "function", "name": choice.name}
    return choice


def _reasoning_of(request: CanonicalRequest) -> dict[str, str] | None:
    if request.reasoning is None:
        return None
    reasoning = {name: value for name, value in (("effort", request.reasoning.effort), ("summary", request.reasoning.summary)) if value is not None}
    return reasoning or None


def body_of(request: CanonicalRequest, upstream_model: str) -> dict[str, Any]:
    unsupported = [name for name, value in (("stop", request.stop), ("seed", request.seed)) if value is not None]
    if unsupported:
        message = f"{', '.join(unsupported)} are not representable by Responses"
        raise UnsupportedFeatureError(message)
    body: dict[str, Any] = {
        "model": upstream_model,
        "input": input_of(request.messages),
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    if request.stream:
        body["stream"] = True
    if request.max_output_tokens is not None:
        body["max_output_tokens"] = request.max_output_tokens
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
    if not isinstance(value, dict):
        message = "expected a JSON object"
        raise TypeError(message)
    if any(not isinstance(key, str) for key in value):
        message = "JSON object keys must be strings"
        raise TypeError(message)
    return cast("dict[str, Any]", value)


def _items(value: object) -> list[object]:
    if not isinstance(value, list):
        message = "expected a list"
        raise TypeError(message)
    return list(value)


def _text(value: object) -> str:
    if not isinstance(value, str):
        message = "expected a string"
        raise TypeError(message)
    return value


def _message(role: object, content: object) -> CanonicalMessage:
    if role == "system":
        return CanonicalSystemMessage.model_validate({"content": content})
    if role == "assistant":
        return CanonicalAssistantMessage.model_validate({"content": content})
    return CanonicalUserMessage.model_validate({"content": content})


def _input_parts(raw_content: object) -> list[CanonicalTextPart | CanonicalImagePart | CanonicalDocumentPart]:
    parts: list[CanonicalTextPart | CanonicalImagePart | CanonicalDocumentPart] = []
    for content in _items(raw_content):
        block = _mapping(content)
        if block.get("type") in {"input_text", "output_text", "text"}:
            parts.append(CanonicalTextPart(text=_text(block.get("text"))))
        elif block.get("type") == "input_image":
            url = _text(block.get("image_url"))
            if url.startswith("data:") and "," in url:
                header, payload = url[5:].split(",", 1)
                parts.append(CanonicalImagePart(data=payload, media_type=header.removesuffix(";base64")))
            elif url:
                parts.append(CanonicalImagePart(url=url))
        elif block.get("type") == "input_file":
            filename = _text(block.get("filename", "")) or None
            if file_id := _text(block.get("file_id", "")):
                parts.append(CanonicalDocumentPart(filename=filename, file_id=file_id))
            elif file_data := _text(block.get("file_data", "")):
                if not file_data.startswith("data:") or ";base64," not in file_data:
                    message = "file_data must be a base64 data URL"
                    raise ValueError(message)
                header, payload = file_data[5:].split(",", 1)
                parts.append(CanonicalDocumentPart(filename=filename, media_type=header.removesuffix(";base64"), data=payload))
            elif file_url := _text(block.get("file_url", "")):
                parts.append(CanonicalDocumentPart(filename=filename, url=file_url))
            else:
                message = "input_file requires file_id, file_data, or file_url"
                raise ValueError(message)
        else:
            message = f"unsupported input content type: {block.get('type')}"
            raise UnsupportedFeatureError(message)

    return parts


def messages_of(value: object) -> list[CanonicalMessage]:
    raw_items = [_mapping(item) for item in _items(value)]
    messages: list[CanonicalMessage] = []
    pending_results: list[CanonicalToolResultPart] = []
    for item in raw_items:
        kind = item.get("type") or ("message" if "role" in item else None)
        if kind == "function_call_output":
            pending_results.append(
                CanonicalToolResultPart(call_id=_text(item.get("call_id")), content=[CanonicalTextPart(text=_text(item.get("output")))])
            )
            continue
        if pending_results:
            messages.append(CanonicalUserMessage(content=pending_results))
            pending_results = []
        if kind == "function_call":
            messages.append(
                CanonicalAssistantMessage(
                    content=[
                        CanonicalToolCallPart(id=_text(item.get("call_id")), name=_text(item.get("name")), arguments=_text(item.get("arguments")))
                    ],
                )
            )
        elif kind == "reasoning":
            messages.append(
                CanonicalAssistantMessage(
                    content=[
                        CanonicalReasoningPart(
                            id=_text(item.get("id")),
                            text="",
                            signature=_text(item.get("encrypted_content", "")) or None,
                        )
                    ],
                )
            )
        elif kind == "message":
            role = item.get("role")
            if role not in ("system", "developer", "user", "assistant"):
                message = "invalid message role"
                raise ValueError(message)
            canonical_role = "system" if role in {"system", "developer"} else role
            raw_content = item.get("content")
            if isinstance(raw_content, str):
                if raw_content:
                    messages.append(_message(canonical_role, [CanonicalTextPart(text=raw_content)]))
                continue
            parts = _input_parts(raw_content)
            if parts:
                messages.append(_message(canonical_role, parts))
        else:
            message = f"unsupported input item type: {kind}"
            raise UnsupportedFeatureError(message)
    if pending_results:
        messages.append(CanonicalUserMessage(content=pending_results))
    return messages


def response_parts(response: UpstreamResponse) -> list[CanonicalAssistantPart]:
    parts: list[CanonicalAssistantPart] = []
    for item in response.output:
        if item.type == "message":
            parts.extend(CanonicalTextPart(text=block.text) for block in item.content if block.type == "output_text")
        elif item.type == "reasoning":
            text = "".join(summary.text for summary in item.summary)
            parts.append(
                CanonicalReasoningPart(
                    id=item.id or None,
                    text=text,
                    signature=item.encrypted_content or None,
                )
            )
        elif item.type == "function_call":
            parts.append(CanonicalToolCallPart(id=item.call_id, name=item.name, arguments=item.arguments))
    return parts


def usage_of(usage: UpstreamUsage | None) -> CanonicalUsage:
    if usage is None:
        return CanonicalUsage(estimated=True)
    return CanonicalUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.input_tokens_details.cached_tokens if usage.input_tokens_details is not None else 0,
    )


def finish_reason(response: UpstreamResponse, parts: Sequence[CanonicalAssistantPart]) -> CanonicalFinishReason:
    if response.status == "incomplete":
        return "content_filter" if response.incomplete_details is not None and response.incomplete_details.reason == "content_filter" else "length"
    return "tool_calls" if any(isinstance(part, CanonicalToolCallPart) for part in parts) else "stop"


def response_metadata(metadata: ResponseMetadata) -> dict[str, Any]:
    return {
        "id": metadata.id,
        "object": "response",
        "created_at": metadata.created_at,
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "model": metadata.model,
        "tools": [],
        "parallel_tool_calls": True,
        "metadata": {},
        "tool_choice": "auto",
        "temperature": 1,
        "top_p": 1,
    }


def output_text(text: str) -> dict[str, Any]:
    return {"type": "output_text", "text": text, "annotations": [], "logprobs": []}


def json_response(metadata: ResponseMetadata, parts: Sequence[CanonicalAssistantPart], finish: str | None, usage: CanonicalUsage) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    for index, part in enumerate(parts):
        if isinstance(part, CanonicalTextPart):
            output.append(
                {
                    "type": "message",
                    "id": f"msg_{index}",
                    "role": "assistant",
                    "status": "completed",
                    "content": [output_text(part.text)],
                }
            )
        elif isinstance(part, CanonicalReasoningPart):
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
        **response_metadata(metadata),
        "status": "incomplete" if incomplete_reason else "completed",
        **({"incomplete_details": {"reason": incomplete_reason}} if incomplete_reason else {}),
        "output": output,
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "total_tokens": usage.input_tokens + usage.output_tokens,
            "input_tokens_details": {"cached_tokens": usage.cache_read_tokens, "cache_write_tokens": usage.cache_write_tokens},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }
