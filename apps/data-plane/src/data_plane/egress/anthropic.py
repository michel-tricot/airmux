"""The Anthropic provider family: transport assembly and stream state.

The JSON spelling lives in formats/anthropic.py. This module owns what is per-provider-call:
endpoint, credential, encoding, and the fold that accumulates the named-event stream for
finalize. Tool-call deltas renumber to tool ordinals, so a caller sees tool 0 first whatever
block index Anthropic used."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from data_plane.canonical import (
    AssistantPart,
    CanonicalChunk,
    CanonicalResponse,
    Delta,
    ReasoningDelta,
    ReasoningPart,
    TextDelta,
    TextPart,
    ToolCallDelta,
    ToolCallPart,
    Usage,
)
from data_plane.egress.base import EgressAdapter, RawEvent, StreamState, UpstreamRequest, UpstreamStreamError, encode
from data_plane.formats.anthropic import (
    MessagesBody,
    UpstreamBlockDelta,
    UpstreamMessage,
    UpstreamStreamEvent,
    UpstreamUsage,
    finish_reason,
    response_parts,
    to_request,
    to_tool_choice,
    to_tools,
    usage_of,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from contract import ModelEntry
    from data_plane.canonical import CanonicalRequest
    from data_plane.egress.base import Ctx

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096  # last resort only: Anthropic requires max_tokens and the catalog may not carry a cap


@dataclass
class _Block:
    """One content block accumulating across the stream; tool blocks carry their ordinal."""

    type: str
    text: str = ""
    signature: str = ""
    tool_id: str = ""
    name: str = ""
    arguments: str = ""
    ordinal: int = 0


@dataclass
class AnthropicStreamState(StreamState):
    ctx: Ctx = field(kw_only=True)
    pending_event: str | None = None  # the SSE event name captured across a read boundary
    response_id: str | None = None
    blocks: dict[int, _Block] = field(default_factory=dict)
    tool_count: int = 0
    stop: str | None = None
    usage: UpstreamUsage | None = None
    usage_final: bool = False  # message_delta carries the real output count; before it, counts are estimates

    @property
    def chunk_id(self) -> str:
        return self.response_id or self.ctx.request_id


def _final_parts(blocks: dict[int, _Block]) -> list[AssistantPart]:
    parts: list[AssistantPart] = []
    for block in (blocks[i] for i in sorted(blocks)):
        if block.type == "thinking":
            parts.append(ReasoningPart(text=block.text, signature=block.signature or None))
        elif block.type == "text":
            parts.append(TextPart(text=block.text))
        elif block.type == "tool_use":
            parts.append(ToolCallPart(id=block.tool_id, name=block.name, arguments=block.arguments or "{}"))
    return parts


def _start_block(state: AnthropicStreamState, event: UpstreamStreamEvent) -> list[CanonicalChunk]:
    opened = event.content_block
    if opened is None:
        return []
    if opened.type == "tool_use":
        ordinal = state.tool_count
        state.tool_count += 1
        state.blocks[event.index] = _Block(type="tool_use", tool_id=opened.id, name=opened.name, ordinal=ordinal)
        return [CanonicalChunk(id=state.chunk_id, delta=ToolCallDelta(index=ordinal, id=opened.id, name=opened.name or None))]
    state.blocks[event.index] = _Block(type=opened.type, text=opened.text or opened.thinking)
    return []


def _block_delta(state: AnthropicStreamState, event: UpstreamStreamEvent) -> list[CanonicalChunk]:
    block = state.blocks.setdefault(event.index, _Block(type="text"))
    delta = UpstreamBlockDelta.model_validate(event.delta)
    out: Delta | None = None
    if delta.type == "text_delta":
        block.text += delta.text
        out = TextDelta(text=delta.text)
    elif delta.type == "thinking_delta":
        block.text += delta.thinking
        out = ReasoningDelta(text=delta.thinking)
    elif delta.type == "signature_delta":
        block.signature += delta.signature
        out = ReasoningDelta(signature=delta.signature)
    elif delta.type == "input_json_delta":
        block.arguments += delta.partial_json
        out = ToolCallDelta(index=block.ordinal, arguments=delta.partial_json)
    return [CanonicalChunk(id=state.chunk_id, delta=out)] if out is not None else []


class AnthropicAdapter(EgressAdapter):
    kind = "anthropic"

    def transform_request(self, req: CanonicalRequest, m: ModelEntry) -> UpstreamRequest:
        """Transport assembly only; every field mapping lives in formats.anthropic."""
        system, messages = to_request(req.messages)
        body = MessagesBody(
            model=m.upstream_model,
            messages=messages,
            max_tokens=req.max_tokens or m.max_output_tokens or DEFAULT_MAX_TOKENS,
            system=system,
            temperature=req.temperature,
            top_p=req.top_p,
            stop_sequences=req.stop,
            tools=to_tools(req.tools),
            tool_choice=to_tool_choice(req.tool_choice),
            stream=req.stream or None,
        )
        headers = {
            "x-api-key": self.credential.reveal(),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        url = str(self.provider.base_url).rstrip("/") + "/messages"
        return UpstreamRequest(method="POST", url=url, headers=headers, body=encode(body, aliases=self.provider.param_aliases, extras=req.extra))

    def transform_response(self, raw: bytes, ctx: Ctx) -> CanonicalResponse:
        message = UpstreamMessage.model_validate_json(raw)
        return CanonicalResponse(
            id=message.id or ctx.request_id,
            model=ctx.model.model_id,
            content=response_parts(message.content),
            finish_reason=finish_reason(message.stop_reason),
            usage=usage_of(message.usage),
        )

    def new_stream_state(self, ctx: Ctx) -> AnthropicStreamState:
        return AnthropicStreamState(ctx=ctx)

    def frame(self, chunk: bytes, state: StreamState) -> Iterator[RawEvent]:
        assert isinstance(state, AnthropicStreamState)  # noqa: S101 state comes from new_stream_state
        state.buffer += chunk
        *lines, state.buffer = state.buffer.split(b"\n")
        for raw_line in lines:
            line = raw_line.rstrip(b"\r")
            if line.startswith(b"event:"):
                state.pending_event = line[len(b"event:") :].strip().decode()
            elif line.startswith(b"data:"):
                yield RawEvent(data=line[len(b"data:") :].strip(), name=state.pending_event)

    def transform_stream_event(self, ev: RawEvent, state: StreamState) -> list[CanonicalChunk]:
        assert isinstance(state, AnthropicStreamState)  # noqa: S101 state comes from new_stream_state
        data = json.loads(ev.data)
        if data.get("type") == "error":
            error = data.get("error") or {}
            raise UpstreamStreamError(code=str(error.get("type") or "upstream_error"), message=str(error.get("message") or ""))
        event = UpstreamStreamEvent.model_validate(data)
        if event.type == "message_start" and event.message is not None:
            state.response_id = event.message.id or None
            state.usage = event.message.usage
            return []
        if event.type == "content_block_start":
            return _start_block(state, event)
        if event.type == "content_block_delta":
            return _block_delta(state, event)
        if event.type == "message_delta":
            stop = event.delta.get("stop_reason")
            if stop:
                state.stop = str(stop)
            if event.usage is not None:
                opened = state.usage or UpstreamUsage()
                state.usage = opened.model_copy(update={"output_tokens": event.usage.output_tokens or opened.output_tokens})
                state.usage_final = True
            return []
        return []

    def finalize(self, state: StreamState) -> CanonicalResponse:
        assert isinstance(state, AnthropicStreamState)  # noqa: S101 state comes from new_stream_state
        return CanonicalResponse(
            id=state.chunk_id,
            model=state.ctx.model.model_id,
            content=_final_parts(state.blocks),
            finish_reason=finish_reason(state.stop),
            usage=usage_of(state.usage) if state.usage_final else Usage(estimated=True),
        )
