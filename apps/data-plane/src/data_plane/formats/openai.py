"""The OpenAI chat format: canonical in and out of OpenAI's JSON spelling, every field by hand.

Two consumers, one spelling: the openai_compatible adapter renders upstream requests and parses
provider responses; the ingress interpretation reads OpenAI-shaped requests and writes
OpenAI-shaped replies. Lenient parse models where providers differ, so a missing field degrades
to a default rather than failing the response."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_plane.canonical import (
    AssistantPart,
    CanonicalMessage,
    CanonicalRequest,
    ContentPart,
    DocumentPart,
    FinishReason,
    GatewayInfo,
    ImagePart,
    NamedTool,
    Part,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolChoice,
    ToolDef,
    ToolResultPart,
    Usage,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

DATA_URL = "data:"


class ChatBody(BaseModel):
    """Every field the gateway can put on an OpenAI chat request. Absent means None, so the omission
    rule is a property of the type rather than a filter at the call site."""

    model_config = ConfigDict(frozen=True)

    model: str
    messages: list[dict[str, Any]]
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: list[str] | None = None
    seed: int | None = None
    reasoning_effort: str | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    response_format: dict[str, Any] | None = None
    stream: bool | None = None
    stream_options: dict[str, Any] | None = None


def _image_to_url(part: ImagePart) -> str:
    return part.url if part.url is not None else f"{DATA_URL}{part.media_type};base64,{part.data}"


def _document(part: DocumentPart) -> dict[str, Any]:
    file: dict[str, Any] = {}
    if part.filename is not None or part.data is not None:
        file["filename"] = part.filename or "document.pdf"
    if part.file_id is not None:
        file["file_id"] = part.file_id
    elif part.data is not None:
        file["file_data"] = f"{DATA_URL}{part.media_type};base64,{part.data}"
    else:
        file["file_data"] = part.url
    return {"type": "file", "file": file}


def _text_of_parts(parts: Sequence[Part]) -> str:
    return "".join(part.text for part in parts if isinstance(part, TextPart))


def _user_content(parts: Sequence[ContentPart]) -> str | list[dict[str, Any]]:
    if all(isinstance(part, TextPart) for part in parts):
        return _text_of_parts(parts)
    blocks: list[dict[str, Any]] = []
    for part in parts:
        if isinstance(part, TextPart):
            blocks.append({"type": "text", "text": part.text})
        elif isinstance(part, ImagePart):
            blocks.append({"type": "image_url", "image_url": {"url": _image_to_url(part)}})
        elif isinstance(part, DocumentPart):
            blocks.append(_document(part))
    return blocks


def _assistant_message(parts: Sequence[ContentPart]) -> dict[str, Any]:
    calls = [part for part in parts if isinstance(part, ToolCallPart)]
    message: dict[str, Any] = {"role": "assistant", "content": _text_of_parts(parts) or None}
    if calls:
        message["tool_calls"] = [{"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}} for call in calls]
    return message


def to_messages(messages: Sequence[CanonicalMessage]) -> list[dict[str, Any]]:
    """Canonical into OpenAI's wire messages. Tool result parts expand back into their own tool
    messages, and reasoning is dropped: OpenAI does not accept it back on a later turn."""
    out: list[dict[str, Any]] = []
    for message in messages:
        results = [part for part in message.content if isinstance(part, ToolResultPart)]
        rest: list[ContentPart] = [part for part in message.content if not isinstance(part, ToolResultPart)]
        out.extend({"role": "tool", "tool_call_id": result.call_id, "content": _text_of_parts(result.content)} for result in results)
        if not rest:
            continue
        if message.role == "system":
            out.append({"role": "system", "content": _text_of_parts(rest)})
        elif message.role == "assistant":
            out.append(_assistant_message(rest))
        else:
            out.append({"role": "user", "content": _user_content(rest)})
    return out


def to_tools(tools: Sequence[ToolDef] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                **({"description": tool.description} if tool.description else {}),
                "parameters": tool.parameters,
                **({"strict": tool.strict} if tool.strict is not None else {}),
            },
        }
        for tool in tools
    ]


def to_tool_choice(choice: ToolChoice | None) -> str | dict[str, Any] | None:
    if choice is None:
        return None
    if isinstance(choice, NamedTool):
        return {"type": "function", "function": {"name": choice.name}}
    return choice


def _response_format(req: CanonicalRequest) -> dict[str, Any] | None:
    if req.response_format is None:
        return None
    response_format = req.response_format.model_dump(exclude_none=True)
    if response_format.get("type") == "json_schema":
        json_schema = dict(response_format.get("json_schema") or {})
        json_schema.setdefault("name", "response")
        response_format["json_schema"] = json_schema
    return response_format


def body_of(req: CanonicalRequest, upstream_model: str) -> ChatBody:
    """The one place canonical becomes an OpenAI chat body, every field mapped by hand.

    A name matching across the two schemas is coincidence, not a rule: this list is where a
    provider's spelling differences and profile-driven aliases apply, so it never gets replaced
    by a reflective copy."""
    return ChatBody(
        model=upstream_model,
        messages=to_messages(req.messages),
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        top_p=req.top_p,
        stop=req.stop,
        seed=req.seed,
        reasoning_effort=req.reasoning.effort if req.reasoning is not None else None,
        tools=to_tools(req.tools),
        tool_choice=to_tool_choice(req.tool_choice),
        parallel_tool_calls=req.parallel_tool_calls,
        response_format=_response_format(req),
        stream=req.stream or None,
        stream_options={"include_usage": True} if req.stream else None,
    )


# What comes back. Lenient where providers differ: a missing field degrades to a default
# rather than failing the response.


class UpstreamFunction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    arguments: str = ""


class UpstreamErrorDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str | None = None
    message: str = ""


class UpstreamErrorBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: UpstreamErrorDetail

    @model_validator(mode="before")
    @classmethod
    def normalize_error(cls, value: object) -> object:
        if isinstance(value, str):
            return {"error": {"message": value}}
        if not isinstance(value, dict):
            return value
        error = value.get("error")
        if isinstance(error, str):
            code = value.get("code")
            return {
                "error": {
                    "code": str(code) if code is not None else None,
                    "message": error,
                }
            }
        if isinstance(error, dict):
            code = error.get("code")
            return {**value, "error": {**error, **({"code": str(code)} if code is not None else {})}}
        if error is not None:
            return value
        message = value.get("message")
        if not isinstance(message, str) and "detail" in value:
            message = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        code = value.get("code")
        return {"error": {"code": str(code) if code is not None else None, "message": message}} if isinstance(message, str) else value


class UpstreamToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    function: UpstreamFunction = Field(default_factory=UpstreamFunction)


class UpstreamMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str | None = None
    reasoning_content: str | None = None
    reasoning: str | None = None
    tool_calls: list[UpstreamToolCall] | None = None


class UpstreamChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: UpstreamMessage
    finish_reason: str


class UpstreamTokenDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cached_tokens: int = 0


class UpstreamUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_tokens_details: UpstreamTokenDetails | None = None


class UpstreamCompletion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    choices: list[UpstreamChoice] = Field(min_length=1)
    usage: UpstreamUsage | None = None


class UpstreamToolCallDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = 0
    id: str | None = None
    function: UpstreamFunction = Field(default_factory=UpstreamFunction)


class UpstreamDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str | None = None
    reasoning_content: str | None = None
    reasoning: str | None = None
    tool_calls: list[UpstreamToolCallDelta] | None = None


class UpstreamChunkChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    delta: UpstreamDelta = Field(default_factory=UpstreamDelta)
    finish_reason: str | None = None


class UpstreamChunk(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    choices: list[UpstreamChunkChoice] = Field(default_factory=list)
    usage: UpstreamUsage | None = None


FINISH_REASONS: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "content_filter": "content_filter",
}


def finish_reason(raw: str | None) -> FinishReason | None:
    """A buffered response always finished; an unrecognized provider spelling reads as a plain stop."""
    if raw is None:
        return None
    return FINISH_REASONS.get(raw, "stop")


def response_parts(message: UpstreamMessage) -> list[AssistantPart]:
    """Order is reasoning, then text, then tool calls; empty parts are omitted so the streaming and
    non-streaming paths agree."""
    parts: list[AssistantPart] = []
    if reasoning := message.reasoning_content or message.reasoning:
        parts.append(ReasoningPart(text=reasoning))
    if message.content:
        parts.append(TextPart(text=message.content))
    parts.extend(ToolCallPart(id=call.id, name=call.function.name, arguments=call.function.arguments) for call in message.tool_calls or [])
    return parts


def usage_of(reported: UpstreamUsage | None) -> Usage:
    """OpenAI counts cache hits inside prompt_tokens, the convention canonical already uses.

    A usage block with no recognizable counts reads as absent: a provider reporting usage in an
    unknown shape must surface as an estimate, never as a free request."""
    if reported is None or (reported.prompt_tokens == 0 and reported.completion_tokens == 0):
        return Usage(estimated=True)
    return Usage(
        input_tokens=reported.prompt_tokens,
        output_tokens=reported.completion_tokens,
        cache_read_tokens=reported.prompt_tokens_details.cached_tokens if reported.prompt_tokens_details is not None else 0,
    )


# The ingress direction: OpenAI-shaped requests into canonical, canonical replies into the
# shapes the official SDKs deserialize.


def _mapping(value: object) -> dict[str, object]:
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _image_from_url(url: str) -> ImagePart:
    if not url.startswith(DATA_URL):
        return ImagePart(url=url)
    header, _, payload = url[len(DATA_URL) :].partition(",")
    return ImagePart(media_type=header.removesuffix(";base64"), data=payload)


def _document_from_file(value: object) -> DocumentPart:
    file = _mapping(value)
    filename = _str(file.get("filename")) or None
    if file_id := _str(file.get("file_id")):
        return DocumentPart(filename=filename, file_id=file_id)
    file_data = _str(file.get("file_data"))
    if file_data.startswith(DATA_URL) and "," in file_data:
        header, payload = file_data[len(DATA_URL) :].split(",", 1)
        return DocumentPart(filename=filename, media_type=header.removesuffix(";base64"), data=payload)
    return DocumentPart(filename=filename, url=file_data)


def _text_of(content: object) -> str:
    """OpenAI spells a message body as either a string or a block list; both reduce to their text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_str(_mapping(block).get("text")) for block in content if _mapping(block).get("type") == "text")
    return ""


def _user_parts(content: object) -> list[ContentPart]:
    if isinstance(content, str):
        return [TextPart(text=content)] if content else []
    if not isinstance(content, list):
        return []
    parts: list[ContentPart] = []
    for raw in content:
        block = _mapping(raw)
        if block.get("type") == "text":
            parts.append(TextPart(text=_str(block.get("text"))))
        elif block.get("type") == "image_url":
            parts.append(_image_from_url(_str(_mapping(block.get("image_url")).get("url"))))
        elif block.get("type") == "file":
            parts.append(_document_from_file(block.get("file")))
    return parts


def _assistant_parts(message: dict[str, object]) -> list[ContentPart]:
    parts: list[ContentPart] = []
    if reasoning := _str(message.get("reasoning_content")) or _str(message.get("reasoning")):
        parts.append(ReasoningPart(text=reasoning))
    if text := _text_of(message.get("content")):
        parts.append(TextPart(text=text))
    calls = message.get("tool_calls")
    for raw in calls if isinstance(calls, list) else []:
        call = _mapping(raw)
        function = _mapping(call.get("function"))
        parts.append(ToolCallPart(id=_str(call.get("id")), name=_str(function.get("name")), arguments=_str(function.get("arguments"))))
    return parts


def from_messages(messages: object) -> list[CanonicalMessage]:
    """OpenAI's wire messages into canonical. A tool message becomes a tool result part on a user
    message, and consecutive tool messages merge into one so a parallel call's results stay one turn."""
    out: list[CanonicalMessage] = []
    pending: list[ContentPart] = []

    def flush() -> None:
        if pending:
            out.append(CanonicalMessage(role="user", content=list(pending)))
            pending.clear()

    for raw in messages if isinstance(messages, list) else []:
        message = _mapping(raw)
        role = message.get("role")
        if role == "tool":
            pending.append(ToolResultPart(call_id=_str(message.get("tool_call_id")), content=[TextPart(text=_text_of(message.get("content")))]))
            continue
        flush()
        if role in {"system", "developer"}:
            out.append(CanonicalMessage(role="system", content=[TextPart(text=_text_of(message.get("content")))]))
        elif role == "assistant":
            out.append(CanonicalMessage(role="assistant", content=_assistant_parts(message)))
        else:
            out.append(CanonicalMessage(role="user", content=_user_parts(message.get("content"))))
    flush()
    return out


def from_tools(tools: object) -> list[ToolDef] | None:
    if not isinstance(tools, list) or not tools:
        return None
    defs: list[ToolDef] = []
    for raw in tools:
        function = _mapping(_mapping(raw).get("function"))
        defs.append(
            ToolDef(
                name=_str(function.get("name")),
                description=_str(function.get("description")) or None,
                parameters=dict(_mapping(function.get("parameters"))),
                strict=_bool(function.get("strict")),
            )
        )
    return defs


def from_tool_choice(choice: object) -> ToolChoice | None:
    if choice == "auto":
        return "auto"
    if choice == "none":
        return "none"
    if choice == "required":
        return "required"
    name = _str(_mapping(_mapping(choice).get("function")).get("name"))
    return NamedTool(name=name) if name else None


class ToolCallOut(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: dict[str, str]


class MessageOut(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str | None
    reasoning_content: str | None = None
    tool_calls: list[ToolCallOut] | None = None


class ChoiceOut(BaseModel):
    index: int = 0
    message: MessageOut
    finish_reason: str | None


class PromptTokensDetails(BaseModel):
    cached_tokens: int = 0


class UsageOut(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_tokens_details: PromptTokensDetails


class ChatCompletionOut(BaseModel):
    """What an OpenAI SDK deserializes; gateway rides along as an extra field SDKs ignore."""

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChoiceOut]
    usage: UsageOut
    gateway: GatewayInfo | None = None


class ToolCallDeltaOut(BaseModel):
    index: int
    id: str | None = None
    type: Literal["function"] | None = None
    function: dict[str, str] | None = None


class DeltaOut(BaseModel):
    role: Literal["assistant"] | None = None
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[ToolCallDeltaOut] | None = None


class ChunkChoiceOut(BaseModel):
    index: int = 0
    delta: DeltaOut
    finish_reason: str | None = None


class ChatCompletionChunkOut(BaseModel):
    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChunkChoiceOut]
    usage: UsageOut | None = None
    gateway: GatewayInfo | None = None

    def sse(self) -> bytes:
        return b"data: " + self.model_dump_json(exclude_none=True).encode() + b"\n\n"


def usage_out(usage: Usage) -> UsageOut:
    return UsageOut(
        prompt_tokens=usage.input_tokens,
        completion_tokens=usage.output_tokens,
        total_tokens=usage.input_tokens + usage.output_tokens,
        prompt_tokens_details=PromptTokensDetails(cached_tokens=usage.cache_read_tokens),
    )


def to_message(parts: Sequence[ContentPart]) -> MessageOut:
    """Canonical response content as one assistant message. content is null rather than empty when the
    turn is only tool calls, which is the shape OpenAI itself returns."""
    text = _text_of_parts(parts)
    reasoning = "".join(part.text for part in parts if isinstance(part, ReasoningPart))
    calls = [ToolCallOut(id=part.id, function={"name": part.name, "arguments": part.arguments}) for part in parts if isinstance(part, ToolCallPart)]
    return MessageOut(content=text or None, reasoning_content=reasoning or None, tool_calls=calls or None)
