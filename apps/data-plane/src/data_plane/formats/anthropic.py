"""The Anthropic Messages format, both directions the gateway needs.

Two consumers, one spelling: the anthropic egress adapter renders upstream requests and parses
provider responses; the /inf/v1/messages ingress reads Anthropic-shaped requests and writes
Anthropic-shaped replies. Lenient parse models where inputs vary; thinking signatures
round-trip everywhere, because a later turn without one is rejected."""

from __future__ import annotations

import base64
import json
import logging
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from data_plane.canonical import (
    AssistantPart,
    CanonicalMessage,
    ContentPart,
    DocumentPart,
    FinishReason,
    GatewayInfo,
    ImagePart,
    NamedTool,
    ReasoningPart,
    ResponseFormat,
    TextPart,
    ToolCallPart,
    ToolChoice,
    ToolDef,
    ToolResultPart,
    Usage,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from data_plane.canonical import CanonicalRequest

logger = logging.getLogger("data_plane")

CACHE_CONTROL = {"type": "ephemeral"}
REASONING_IDENTITY_PREFIX = "airllm-reasoning-v1:"


def reasoning_signature(reasoning_id: str | None, signature: str | None) -> str:
    if reasoning_id is None:
        return signature or ""
    payload = json.dumps([reasoning_id, signature], separators=(",", ":")).encode()
    return REASONING_IDENTITY_PREFIX + base64.urlsafe_b64encode(payload).decode()


def reasoning_identity(signature: str) -> tuple[str | None, str | None]:
    if not signature.startswith(REASONING_IDENTITY_PREFIX):
        return None, signature or None
    encoded = signature.removeprefix(REASONING_IDENTITY_PREFIX)
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode())
    except (ValueError, UnicodeDecodeError):
        return None, signature
    if not isinstance(payload, list):
        return None, signature
    try:
        reasoning_id, original = payload
    except ValueError:
        return None, signature
    if not isinstance(reasoning_id, str) or (original is not None and not isinstance(original, str)):
        return None, signature
    return reasoning_id, original


class MessagesBody(BaseModel):
    """Every field the gateway can put on an Anthropic Messages request. max_tokens is required
    here and optional on OpenAI, which is the asymmetry the adapter's default covers."""

    model_config = ConfigDict(frozen=True)

    model: str
    messages: list[dict[str, Any]]
    max_tokens: int
    system: str | list[dict[str, Any]] | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop_sequences: list[str] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: dict[str, Any] | None = None
    stream: bool | None = None
    thinking: dict[str, Any] | None = None
    output_config: dict[str, Any] | None = None


def _with_cache(block: dict[str, Any], cache: Literal["ephemeral"] | None) -> dict[str, Any]:
    return {**block, "cache_control": CACHE_CONTROL} if cache else block


def _tool_input(arguments: str) -> dict[str, Any]:
    """A caller's own prior tool call. Unparseable arguments are a corrupt conversation, so this
    refuses rather than sending Anthropic a call with no input that the model would then act on."""
    if not arguments:
        return {}
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as e:
        msg = f"tool call arguments are not valid JSON: {arguments[:120]}"
        raise ValueError(msg) from e
    if isinstance(parsed, dict):
        return parsed
    msg = f"tool call arguments must be a JSON object, got {type(parsed).__name__}"
    raise ValueError(msg)


def _block(part: ContentPart) -> dict[str, Any] | None:
    if isinstance(part, TextPart):
        return _with_cache({"type": "text", "text": part.text}, part.cache)
    if isinstance(part, ReasoningPart):
        thinking: dict[str, Any] = {"type": "thinking", "thinking": part.text}
        if part.signature:
            thinking["signature"] = part.signature
        return _with_cache(thinking, part.cache)
    if isinstance(part, ImagePart):
        source = {"type": "url", "url": part.url} if part.url is not None else {"type": "base64", "media_type": part.media_type, "data": part.data}
        return _with_cache({"type": "image", "source": source}, part.cache)
    if isinstance(part, DocumentPart):
        if part.file_id is not None:
            source = {"type": "file", "file_id": part.file_id}
        elif part.url is not None:
            source = {"type": "url", "url": part.url}
        else:
            source = {"type": "base64", "media_type": part.media_type, "data": part.data}
        return _with_cache({"type": "document", "source": source}, part.cache)
    if isinstance(part, ToolCallPart):
        block = {"type": "tool_use", "id": part.id, "name": part.name, "input": _tool_input(part.arguments)}
    elif isinstance(part, ToolResultPart):
        block = {
            "type": "tool_result",
            "tool_use_id": part.call_id,
            "content": [b for b in (_block(inner) for inner in part.content) if b is not None],
        }
        if part.is_error:
            block["is_error"] = True
    else:
        return None
    return _with_cache(block, part.cache)


def _system_field(parts: Sequence[ContentPart]) -> list[dict[str, Any]] | str | None:
    """Plain text with no cache breakpoint collapses to a string, which is the shape Anthropic
    documents and the one a caller sending a bare system prompt gets back unchanged."""
    if not parts:
        return None
    if all(isinstance(part, TextPart) and part.cache is None for part in parts):
        return "\n".join(part.text for part in parts if isinstance(part, TextPart))
    return [b for b in (_block(part) for part in parts) if b is not None]


def _collapse(blocks: list[dict[str, Any]]) -> list[dict[str, Any]] | str:
    """Plain text collapses to a string for the same reason the system field does."""
    if all(set(block) == {"type", "text"} for block in blocks):
        return "".join(block["text"] for block in blocks)
    return blocks


def to_request(messages: Sequence[CanonicalMessage]) -> tuple[list[dict[str, Any]] | str | None, list[dict[str, Any]]]:
    """Canonical into Anthropic's (system, messages) pair. Consecutive same-role turns merge, because
    Anthropic requires strict user/assistant alternation and a tool result is its own canonical turn."""
    system_parts = [part for message in messages if message.role == "system" for part in message.content]
    system = _system_field(system_parts)

    turns: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            continue
        blocks = [b for b in (_block(part) for part in message.content) if b is not None]
        if not blocks:
            continue
        if turns and turns[-1]["role"] == message.role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": message.role, "content": blocks})
    return system, [{**turn, "content": _collapse(turn["content"])} for turn in turns]


def to_tools(tools: Sequence[ToolDef] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        _with_cache(
            {
                "name": tool.name,
                **({"description": tool.description} if tool.description else {}),
                "input_schema": tool.parameters,
                **({"strict": tool.strict} if tool.strict is not None else {}),
            },
            tool.cache,
        )
        for tool in tools
    ]


def to_tool_choice(choice: ToolChoice | None, parallel: bool | None = None) -> dict[str, Any] | None:
    if choice is None:
        return None
    selected: dict[str, Any]
    if isinstance(choice, NamedTool):
        selected = {"type": "tool", "name": choice.name}
    else:
        selected = {"type": {"auto": "auto", "required": "any", "none": "none"}[choice]}
    if parallel is not None:
        selected["disable_parallel_tool_use"] = not parallel
    return selected


def output_config_of(request: CanonicalRequest) -> dict[str, Any] | None:
    output_config: dict[str, Any] = {}
    if request.reasoning is not None and request.reasoning.effort is not None:
        output_config["effort"] = request.reasoning.effort
    if request.response_format is not None:
        if request.response_format.type == "json_schema":
            schema = request.response_format.json_schema or {}
            output_config["format"] = {"type": "json_schema", "schema": schema.get("schema") or {}}
        elif request.response_format.type == "json_object":
            output_config["format"] = {"type": "json_schema", "schema": {"type": "object"}}
    return output_config or None


def response_format_from(output_config: object) -> ResponseFormat | None:
    if not isinstance(output_config, dict):
        return None
    format_value = output_config.get("format")
    if not isinstance(format_value, dict) or format_value.get("type") != "json_schema":
        return None
    schema = format_value.get("schema") or {}
    if schema == {"type": "object"}:
        return ResponseFormat(type="json_object")
    return ResponseFormat(type="json_schema", json_schema={"name": "response", "strict": True, "schema": schema})


def thinking_of(request: CanonicalRequest) -> dict[str, Any] | None:
    if request.reasoning is None:
        return None
    reasoning_type = request.reasoning.type or ("adaptive" if request.reasoning.effort is not None or request.reasoning.summary is not None else None)
    if reasoning_type is None:
        return None
    return {
        "type": reasoning_type,
        **({"budget_tokens": request.reasoning.budget_tokens} if request.reasoning.budget_tokens is not None else {}),
        **({"display": request.reasoning.display} if request.reasoning.display is not None else {}),
    }


# What comes back. Lenient: a missing field degrades to a default rather than failing the response.


class UpstreamBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = "text"
    text: str = ""
    thinking: str = ""
    signature: str | None = None
    id: str = ""
    name: str = ""
    input: dict[str, Any] = Field(default_factory=dict)


class UpstreamErrorDetail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = "upstream_error"
    message: str = ""


class UpstreamErrorBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["error"] = "error"
    error: UpstreamErrorDetail


class UpstreamUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class UpstreamMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    content: list[UpstreamBlock] = Field(default_factory=list)
    stop_reason: str | None = None
    usage: UpstreamUsage | None = None


class UpstreamCompletedMessage(UpstreamMessage):
    content: list[UpstreamBlock]
    stop_reason: str


STOP_REASONS: dict[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "pause_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "refusal": "content_filter",
}


def finish_reason(raw: str | None) -> FinishReason | None:
    """A buffered response always finished; an unrecognized provider spelling reads as a plain stop."""
    if raw is None:
        return None
    return STOP_REASONS.get(raw, "stop")


def response_parts(blocks: Sequence[UpstreamBlock]) -> list[AssistantPart]:
    """Anthropic already orders blocks the way canonical does: reasoning, then text, then tools.
    Signatures ride with the reasoning; a redacted_thinking block has no canonical carrier yet
    and is skipped."""
    parts: list[AssistantPart] = []
    for block in blocks:
        if block.type == "thinking":
            parts.append(ReasoningPart(text=block.thinking, signature=block.signature))
        elif block.type == "text":
            parts.append(TextPart(text=block.text))
        elif block.type == "tool_use":
            parts.append(ToolCallPart(id=block.id, name=block.name, arguments=json.dumps(block.input)))
    return parts


def usage_of(reported: UpstreamUsage | None) -> Usage:
    """Anthropic reports cache traffic beside input_tokens; canonical counts it inside.

    A usage block with no recognizable counts reads as absent: an unknown reporting shape must
    surface as an estimate, never as a free request."""
    if reported is None or (reported.input_tokens == 0 and reported.output_tokens == 0):
        return Usage(estimated=True)
    return Usage(
        input_tokens=reported.input_tokens + reported.cache_read_input_tokens + reported.cache_creation_input_tokens,
        output_tokens=reported.output_tokens,
        cache_read_tokens=reported.cache_read_input_tokens,
        cache_write_tokens=reported.cache_creation_input_tokens,
    )


# Stream events, as parsed. Anthropic names each SSE event after its payload type.


class UpstreamBlockDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = ""
    text: str = ""
    thinking: str = ""
    partial_json: str = ""
    signature: str = ""


class UpstreamStreamEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    index: int = 0
    message: UpstreamMessage | None = None
    content_block: UpstreamBlock | None = None
    delta: dict[str, Any] = Field(default_factory=dict)
    usage: UpstreamUsage | None = None


# The ingress direction: Anthropic-shaped requests into canonical, canonical replies into the
# shapes the official SDKs and Claude Code deserialize.


def _mapping(value: object) -> dict[str, object]:
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _cache_of(block: dict[str, object]) -> Literal["ephemeral"] | None:
    return "ephemeral" if block.get("cache_control") else None


def _is_directive(block: dict[str, object]) -> bool:
    """Anthropic clients smuggle protocol metadata as a system text block. It is not prompt content, and
    forwarding it breaks prefix caching for a provider that caches by exact prefix, since it changes per call."""
    text = block.get("text")
    return isinstance(text, str) and text.lstrip().lower().startswith("x-anthropic-")


def _image_from_source(source: dict[str, object]) -> ImagePart:
    if source.get("type") == "url":
        return ImagePart(url=_str(source.get("url")))
    return ImagePart(media_type=_str(source.get("media_type")), data=_str(source.get("data")))


def _document_from_source(source: dict[str, object]) -> DocumentPart:
    if source.get("type") == "url":
        return DocumentPart(url=_str(source.get("url")))
    if source.get("type") == "file":
        return DocumentPart(file_id=_str(source.get("file_id")))
    return DocumentPart(media_type=_str(source.get("media_type")), data=_str(source.get("data")))


def _tool_result_content(content: object) -> list[TextPart | ImagePart]:
    if isinstance(content, str):
        return [TextPart(text=content)]
    if not isinstance(content, list):
        return []
    parts: list[TextPart | ImagePart] = []
    for raw in content:
        block = _mapping(raw)
        if block.get("type") == "text":
            parts.append(TextPart(text=_str(block.get("text"))))
        elif block.get("type") == "image":
            parts.append(_image_from_source(_mapping(block.get("source"))))
    return parts


def _parts_from_blocks(content: object) -> list[ContentPart]:
    if isinstance(content, str):
        return [TextPart(text=content)] if content else []
    if not isinstance(content, list):
        return []
    parts: list[ContentPart] = []
    for raw in content:
        block = _mapping(raw)
        if _is_directive(block):
            continue
        cache = _cache_of(block)
        kind = block.get("type")
        if kind == "text":
            parts.append(TextPart(text=_str(block.get("text")), cache=cache))
        elif kind == "thinking":
            reasoning_id, signature = reasoning_identity(_str(block.get("signature")))
            parts.append(ReasoningPart(id=reasoning_id, text=_str(block.get("thinking")), signature=signature, cache=cache))
        elif kind == "image":
            parts.append(_image_from_source(_mapping(block.get("source"))).model_copy(update={"cache": cache}))
        elif kind == "document":
            parts.append(_document_from_source(_mapping(block.get("source"))).model_copy(update={"cache": cache}))
        elif kind == "tool_use":
            parts.append(
                ToolCallPart(
                    id=_str(block.get("id")),
                    name=_str(block.get("name")),
                    arguments=json.dumps(dict(_mapping(block.get("input")))),
                    cache=cache,
                )
            )
        elif kind == "tool_result":
            parts.append(
                ToolResultPart(
                    call_id=_str(block.get("tool_use_id")),
                    content=_tool_result_content(block.get("content")),
                    is_error=bool(block.get("is_error")),
                    cache=cache,
                )
            )
    return parts


def from_request(data: dict[str, object]) -> list[CanonicalMessage]:
    """Anthropic's Messages body into canonical, with the out-of-band system prompt as the first message."""
    messages: list[CanonicalMessage] = []
    system = _parts_from_blocks(data.get("system"))
    if system:
        messages.append(CanonicalMessage(role="system", content=system))
    raw_messages = data.get("messages")
    for raw in raw_messages if isinstance(raw_messages, list) else []:
        message = _mapping(raw)
        parts = _parts_from_blocks(message.get("content"))
        if parts:
            messages.append(CanonicalMessage(role="assistant" if message.get("role") == "assistant" else "user", content=parts))
    return messages


def from_tools(tools: object) -> list[ToolDef] | None:
    if not isinstance(tools, list) or not tools:
        return None
    return [
        ToolDef(
            name=_str(_mapping(tool).get("name")),
            description=_str(_mapping(tool).get("description")) or None,
            parameters=dict(_mapping(_mapping(tool).get("input_schema"))),
            cache=_cache_of(_mapping(tool)),
            strict=_bool(_mapping(tool).get("strict")),
        )
        for tool in tools
    ]


def from_tool_choice(choice: object) -> ToolChoice | None:
    block = _mapping(choice)
    kind = block.get("type")
    name = _str(block.get("name"))
    if kind == "tool" and name:
        return NamedTool(name=name)
    if kind == "auto":
        return "auto"
    if kind == "any":
        return "required"
    if kind == "none":
        return "none"
    return None


# Render models: what an Anthropic client deserializes. Signatures ride with the thinking.

REVERSE_STOP: dict[str, str] = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use", "content_filter": "refusal"}


def stop_reason(finish: FinishReason | None) -> str | None:
    """None when the reason is unknown, which is what a cancelled or failed response has; claiming
    end_turn would tell the caller a truncated answer is complete."""
    return REVERSE_STOP.get(finish) if finish else None


class TextOut(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ThinkingOut(BaseModel):
    type: Literal["thinking"] = "thinking"
    thinking: str
    signature: str = ""


class ToolUseOut(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any]


BlockOut = TextOut | ThinkingOut | ToolUseOut


def _response_tool_input(arguments: str) -> dict[str, Any]:
    """The render-side parse, where the arguments came from a provider and the response already
    exists. Refusing would turn a delivered answer into a 502, so this reports and continues."""
    try:
        return _tool_input(arguments)
    except ValueError:
        logger.warning("upstream tool call arguments did not parse; rendering empty input")
        return {}


def to_response_content(parts: Sequence[AssistantPart]) -> list[BlockOut]:
    blocks: list[BlockOut] = []
    for part in parts:
        if isinstance(part, ReasoningPart):
            blocks.append(ThinkingOut(thinking=part.text, signature=reasoning_signature(part.id, part.signature)))
        elif isinstance(part, TextPart):
            blocks.append(TextOut(text=part.text))
        elif isinstance(part, ToolCallPart):
            blocks.append(ToolUseOut(id=part.id, name=part.name, input=_response_tool_input(part.arguments)))
    return blocks


class UsageOut(BaseModel):
    """Anthropic reports fresh input separately from cache traffic. The floor guards a provider that
    reports more cache than total: a negative count would corrupt the caller's cost arithmetic."""

    input_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    output_tokens: int


def usage_out(usage: Usage) -> UsageOut:
    fresh = usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens
    if fresh < 0:
        logger.warning(
            "provider reported cache tokens above total input: input=%d read=%d write=%d",
            usage.input_tokens,
            usage.cache_read_tokens,
            usage.cache_write_tokens,
        )
    return UsageOut(
        input_tokens=max(0, fresh),
        cache_read_input_tokens=usage.cache_read_tokens,
        cache_creation_input_tokens=usage.cache_write_tokens,
        output_tokens=usage.output_tokens,
    )


class MessageOut(BaseModel):
    """What an Anthropic client deserializes; gateway rides along as an extra field SDKs ignore."""

    id: str
    type: Literal["message"] = "message"
    role: Literal["assistant"] = "assistant"
    model: str
    content: list[BlockOut]
    stop_reason: str | None
    stop_sequence: str | None = None
    usage: UsageOut
    gateway: GatewayInfo | None = None


class TextDeltaOut(BaseModel):
    type: Literal["text_delta"] = "text_delta"
    text: str


class ThinkingDeltaOut(BaseModel):
    type: Literal["thinking_delta"] = "thinking_delta"
    thinking: str


class SignatureDeltaOut(BaseModel):
    type: Literal["signature_delta"] = "signature_delta"
    signature: str


class InputJsonDeltaOut(BaseModel):
    type: Literal["input_json_delta"] = "input_json_delta"
    partial_json: str


DeltaOut = TextDeltaOut | ThinkingDeltaOut | SignatureDeltaOut | InputJsonDeltaOut


class StopDeltaOut(BaseModel):
    stop_reason: str | None
    stop_sequence: str | None = None


class ErrorOut(BaseModel):
    type: str
    message: str


class Event(BaseModel):
    """One named SSE event. Anthropic names the event after its type, so the frame needs no second label."""

    type: str

    def sse(self) -> bytes:
        return b"event: " + self.type.encode() + b"\ndata: " + self.model_dump_json().encode() + b"\n\n"


class StartUsage(BaseModel):
    """What is knowable when the stream opens, which is nothing: real counts land in message_delta."""

    input_tokens: int = 0
    output_tokens: int = 0


class MessageStartOut(BaseModel):
    id: str
    type: Literal["message"] = "message"
    role: Literal["assistant"] = "assistant"
    model: str
    content: list[BlockOut] = Field(default_factory=list)
    stop_reason: str | None = None
    stop_sequence: str | None = None
    usage: StartUsage = Field(default_factory=StartUsage)


class MessageStart(Event):
    type: Literal["message_start"] = "message_start"
    message: MessageStartOut


class Ping(Event):
    type: Literal["ping"] = "ping"


class ContentBlockStart(Event):
    type: Literal["content_block_start"] = "content_block_start"
    index: int
    content_block: BlockOut


class ContentBlockDelta(Event):
    type: Literal["content_block_delta"] = "content_block_delta"
    index: int
    delta: DeltaOut


class ContentBlockStop(Event):
    type: Literal["content_block_stop"] = "content_block_stop"
    index: int


class MessageDelta(Event):
    type: Literal["message_delta"] = "message_delta"
    delta: StopDeltaOut
    usage: UsageOut
    gateway: GatewayInfo | None = None


class MessageStop(Event):
    type: Literal["message_stop"] = "message_stop"


class ErrorEvent(Event):
    type: Literal["error"] = "error"
    error: ErrorOut
