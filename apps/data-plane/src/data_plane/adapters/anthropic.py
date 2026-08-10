from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from data_plane.adapters.base import ProviderAdapter
from data_plane.adapters.shape import content_blocks
from data_plane.canonical import CanonicalChunk, CanonicalResponse, RawEvent, StreamState, UpstreamRequest, UpstreamStreamError, Usage

if TYPE_CHECKING:
    from collections.abc import Iterator

    from contract import ModelEntry
    from data_plane.canonical import CanonicalRequest, Ctx

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096

# Anthropic stop reasons -> the canonical set the OpenAI adapter already emits, so finish_reason is provider-agnostic.
STOP_REASONS = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls"}


def _usage(reported: dict[str, Any]) -> Usage:
    """Anthropic splits prompt tokens across fresh/cache-read/cache-write; keep the split for cost."""
    read = reported.get("cache_read_input_tokens", 0)
    write = reported.get("cache_creation_input_tokens", 0)
    return Usage(
        input_tokens=reported.get("input_tokens", 0) + read + write,
        output_tokens=reported.get("output_tokens", 0),
        cache_read_tokens=read,
        cache_write_tokens=write,
        estimated=not reported,
    )


@dataclass
class _Block:
    type: str
    text: str = ""
    tool_id: str | None = None
    name: str = ""
    arguments: str = ""


@dataclass
class AnthropicStreamState(StreamState):
    ctx: Ctx = field(kw_only=True)
    pending_event: str | None = None  # the SSE event name captured across a read boundary
    response_id: str | None = None
    blocks: dict[int, _Block] = field(default_factory=dict)
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    saw_usage: bool = False

    @property
    def chunk_id(self) -> str:
        return self.response_id or self.ctx.request_id


def _ordered(blocks: dict[int, _Block]) -> list[_Block]:
    return [blocks[i] for i in sorted(blocks)]


def _finalize_blocks(blocks: dict[int, _Block]) -> list[dict[str, Any]]:
    ordered = _ordered(blocks)
    reasoning = "".join(b.text for b in ordered if b.type == "thinking")
    text = "".join(b.text for b in ordered if b.type == "text")
    tool_calls = [{"id": b.tool_id, "function": {"name": b.name, "arguments": b.arguments}} for b in ordered if b.type == "tool_use"]
    return content_blocks(reasoning, text, tool_calls)


def _to_anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    fn = tool.get("function") or tool
    out = {"name": fn.get("name"), "description": fn.get("description", ""), "input_schema": fn.get("parameters") or fn.get("input_schema") or {}}
    if tool.get("cache_control"):
        out["cache_control"] = tool["cache_control"]
    return out


def _system_field(messages: list[dict[str, Any]]) -> object:
    """Hoist system messages to Anthropic's top-level system, keeping cache_control blocks intact."""
    blocks: list[dict[str, Any]] = []
    structured = False
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            structured = True
            blocks.extend(content)
        elif content:
            blocks.append({"type": "text", "text": str(content)})
    if not blocks:
        return None
    if structured:
        return blocks
    return "\n".join(b["text"] for b in blocks)


def _start_block(state: AnthropicStreamState, data: dict[str, Any]) -> list[CanonicalChunk]:
    index = data.get("index", 0)
    block = data.get("content_block") or {}
    btype = block.get("type", "text")
    if btype == "tool_use":
        state.blocks[index] = _Block(type="tool_use", tool_id=block.get("id"), name=block.get("name", ""))
        delta = {"type": "tool_call", "index": index, "id": block.get("id"), "function": {"name": block.get("name", ""), "arguments": ""}}
        return [CanonicalChunk(id=state.chunk_id, delta=delta)]
    state.blocks[index] = _Block(type=btype, text=block.get("text") or block.get("thinking") or "")
    return []


def _block_delta(state: AnthropicStreamState, data: dict[str, Any]) -> list[CanonicalChunk]:
    index = data.get("index", 0)
    delta = data.get("delta") or {}
    block = state.blocks.setdefault(index, _Block(type="text"))
    dtype = delta.get("type")
    if dtype == "text_delta":
        block.text += delta.get("text", "")
        return [CanonicalChunk(id=state.chunk_id, delta={"type": "text", "text": delta.get("text", "")})]
    if dtype == "thinking_delta":
        block.text += delta.get("thinking", "")
        return [CanonicalChunk(id=state.chunk_id, delta={"type": "reasoning", "text": delta.get("thinking", "")})]
    if dtype == "input_json_delta":
        fragment = delta.get("partial_json", "")
        block.arguments += fragment
        return [CanonicalChunk(id=state.chunk_id, delta={"type": "tool_call", "index": index, "function": {"arguments": fragment}})]
    return []


class AnthropicAdapter(ProviderAdapter):
    kind = "anthropic"

    def transform_request(self, req: CanonicalRequest, m: ModelEntry) -> UpstreamRequest:
        system = _system_field([msg for msg in req.messages if msg.get("role") == "system"])
        body: dict[str, Any] = {
            "model": m.upstream_model,
            "messages": [msg for msg in req.messages if msg.get("role") != "system"],
            "max_tokens": req.max_tokens or DEFAULT_MAX_TOKENS,
        }
        if system:
            body["system"] = system
        if req.temperature is not None:
            body["temperature"] = req.temperature
        if req.tools:
            body["tools"] = [_to_anthropic_tool(t) for t in req.tools]
        if req.stream:
            body["stream"] = True
        headers = {
            "x-api-key": self.credential.reveal(),
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        url = str(self.provider.base_url).rstrip("/") + "/messages"
        return UpstreamRequest(method="POST", url=url, headers=headers, body=json.dumps(body).encode("utf-8"))

    def transform_response(self, raw: bytes, ctx: Ctx) -> CanonicalResponse:
        data = json.loads(raw)
        reasoning = "".join(b["thinking"] for b in data["content"] if b.get("type") == "thinking")
        text = "".join(b["text"] for b in data["content"] if b.get("type") == "text")
        tool_calls = [
            {"id": b["id"], "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
            for b in data["content"]
            if b.get("type") == "tool_use"
        ]
        usage = data.get("usage") or {}
        return CanonicalResponse(
            id=data.get("id", ctx.request_id),
            model=ctx.model.model_id,
            content=content_blocks(reasoning, text, tool_calls),
            finish_reason=STOP_REASONS.get(data.get("stop_reason"), data.get("stop_reason")),
            usage=_usage(usage),
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
        kind = data.get("type")
        if kind == "error":
            error = data.get("error") or {}
            raise UpstreamStreamError(code=str(error.get("type") or "upstream_error"), message=str(error.get("message") or ""))
        if kind == "message_start":
            message = data.get("message") or {}
            state.response_id = message.get("id")
            usage = message.get("usage") or {}
            state.cache_read_tokens = usage.get("cache_read_input_tokens", 0)
            state.cache_write_tokens = usage.get("cache_creation_input_tokens", 0)
            state.input_tokens = usage.get("input_tokens", 0) + state.cache_read_tokens + state.cache_write_tokens
            state.output_tokens = usage.get("output_tokens", 0)
            state.saw_usage = state.saw_usage or bool(usage)
            return []
        if kind == "content_block_start":
            return _start_block(state, data)
        if kind == "content_block_delta":
            return _block_delta(state, data)
        if kind == "message_delta":
            delta = data.get("delta") or {}
            if delta.get("stop_reason"):
                state.stop_reason = STOP_REASONS.get(delta["stop_reason"], delta["stop_reason"])
            usage = data.get("usage") or {}
            if usage:
                state.output_tokens = usage.get("output_tokens", state.output_tokens)
                state.saw_usage = True
            return []
        return []

    def finalize(self, state: StreamState) -> CanonicalResponse:
        """Return a valid CanonicalResponse at ANY point in the stream.

        Called after the last event for a normal completion, and from the
        cancellation handler for partial accounting after a client disconnect.
        """
        assert isinstance(state, AnthropicStreamState)  # noqa: S101 state comes from new_stream_state
        return CanonicalResponse(
            id=state.chunk_id,
            model=state.ctx.model.model_id,
            content=_finalize_blocks(state.blocks),
            finish_reason=state.stop_reason,
            usage=Usage(
                input_tokens=state.input_tokens,
                output_tokens=state.output_tokens,
                cache_read_tokens=state.cache_read_tokens,
                cache_write_tokens=state.cache_write_tokens,
                estimated=not state.saw_usage,
            ),
        )
