"""The Anthropic Messages format: canonical into Anthropic's JSON spelling, and back out.

One consumer today, the anthropic egress adapter; the /v1/messages ingress joins later. The
request direction renders by hand, field by field. The Upstream* models parse what the
provider returns, lenient so a missing field degrades to a default rather than failing the
response. Thinking signatures round-trip: a signature the provider issues comes back as part
of the reasoning, because a later turn without it is rejected."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from data_plane.canonical import (
    AssistantPart,
    CanonicalMessage,
    ContentPart,
    FinishReason,
    ImagePart,
    NamedTool,
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

logger = logging.getLogger("data_plane")

CACHE_CONTROL = {"type": "ephemeral"}


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
    if isinstance(part, ToolCallPart):
        return _with_cache({"type": "tool_use", "id": part.id, "name": part.name, "input": _tool_input(part.arguments)}, part.cache)
    if isinstance(part, ToolResultPart):
        result: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": part.call_id,
            "content": [b for b in (_block(inner) for inner in part.content) if b is not None],
        }
        if part.is_error:
            result["is_error"] = True
        return _with_cache(result, part.cache)
    return None


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
            {"name": tool.name, **({"description": tool.description} if tool.description else {}), "input_schema": tool.parameters}, tool.cache
        )
        for tool in tools
    ]


def to_tool_choice(choice: ToolChoice | None) -> dict[str, Any] | None:
    if choice is None:
        return None
    if isinstance(choice, NamedTool):
        return {"type": "tool", "name": choice.name}
    return {"auto": {"type": "auto"}, "required": {"type": "any"}, "none": {"type": "none"}}[choice]


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

    type: str = ""
    index: int = 0
    message: UpstreamMessage | None = None
    content_block: UpstreamBlock | None = None
    delta: dict[str, Any] = Field(default_factory=dict)
    usage: UpstreamUsage | None = None
