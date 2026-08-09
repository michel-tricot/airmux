from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse, Response

from data_plane.canonical import CanonicalRequest
from data_plane.ingress.base import EgressStream, Ingress

if TYPE_CHECKING:
    from data_plane.canonical import CanonicalChunk, CanonicalError, CanonicalResponse, Ctx, Usage

# Canonical finish reasons (the OpenAI-ish set the adapters emit) -> Anthropic stop reasons.
REVERSE_STOP = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}


def _event(name: str, payload: dict) -> bytes:
    return b"event: " + name.encode() + b"\ndata: " + json.dumps(payload, ensure_ascii=False).encode() + b"\n\n"


def _has_cache_control(blocks: object) -> bool:
    return isinstance(blocks, list) and any(isinstance(b, dict) and "cache_control" in b for b in blocks)


def _is_directive(block: object) -> bool:
    """Anthropic clients smuggle protocol metadata (e.g. a per-request x-anthropic-billing-header) as a system

    text block. It is not prompt content; forwarding it verbatim would, for a provider that caches by exact
    prefix, break caching on every request since it changes each call. Drop the whole x-anthropic-* namespace.
    """
    if not isinstance(block, dict):
        return False
    text = block.get("text")
    return isinstance(text, str) and text.lstrip().lower().startswith("x-anthropic-")


def _system_message(system: object) -> dict[str, Any] | None:
    """Preserve block structure when it carries cache_control (for prompt caching), else collapse to a string."""
    if isinstance(system, str):
        return {"role": "system", "content": system} if system else None
    if isinstance(system, list):
        blocks = [b for b in system if not _is_directive(b)]
        if not blocks:
            return None
        if _has_cache_control(blocks):
            return {"role": "system", "content": blocks}
        text = "".join(str(b.get("text", "")) for b in blocks if isinstance(b, dict))
        return {"role": "system", "content": text} if text else None
    return None


def _normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    """A pure text-block list collapses to a string so any provider accepts it; cache_control markers are kept.

    Blocks carrying cache_control (and non-text blocks) pass through untouched, which round-trips
    faithfully only when the model routes to an Anthropic upstream.
    """
    content = message.get("content")
    if isinstance(content, list) and not _has_cache_control(content) and all(isinstance(b, dict) and b.get("type") == "text" for b in content):
        return {**message, "content": "".join(b.get("text", "") for b in content)}
    return message


def _from_anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    canonical = {
        "type": "function",
        "function": {"name": tool.get("name"), "description": tool.get("description", ""), "parameters": tool.get("input_schema") or {}},
    }
    if tool.get("cache_control"):
        canonical["cache_control"] = tool["cache_control"]
    return canonical


def _tool_input(arguments: str) -> dict[str, Any]:
    try:
        return json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return {}


def _usage_payload(usage: Usage) -> dict[str, int]:
    """Anthropic counts cache tokens outside input_tokens; canonical counts them inside."""
    return {
        "input_tokens": usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens,
        "cache_read_input_tokens": usage.cache_read_tokens,
        "cache_creation_input_tokens": usage.cache_write_tokens,
        "output_tokens": usage.output_tokens,
    }


def _input_json(index: int, fragment: str) -> dict[str, Any]:
    return {"type": "content_block_delta", "index": index, "delta": {"type": "input_json_delta", "partial_json": fragment}}


def _to_anthropic_content(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for part in content:
        if part.get("type") == "reasoning":
            blocks.append({"type": "thinking", "thinking": part.get("text", "")})
        elif part.get("type") == "text":
            blocks.append({"type": "text", "text": part.get("text", "")})
        elif part.get("type") == "tool_call":
            fn = part.get("function") or {}
            blocks.append({"type": "tool_use", "id": part.get("id"), "name": fn.get("name", ""), "input": _tool_input(fn.get("arguments", ""))})
    return blocks


class AnthropicEgressStream(EgressStream):
    """Rebuilds Anthropic's named-SSE stream from canonical chunks.

    Input tokens are unknown until the stream ends (chunks carry no usage), so
    message_start reports zero and the real counts land in message_delta; a
    faithful count needs the non-streaming endpoint.
    """

    def __init__(self) -> None:
        self.open: tuple[int, str] | None = None  # (anthropic block index, kind)
        self.next_index = 0
        self.tool_blocks: dict[int, int] = {}  # canonical tool index -> anthropic block index
        self.stop_reason = "end_turn"

    def start(self, ctx: Ctx) -> list[bytes]:
        message = {
            "id": ctx.request_id,
            "type": "message",
            "role": "assistant",
            "model": ctx.model.model_id,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
        return [_event("message_start", {"type": "message_start", "message": message}), _event("ping", {"type": "ping"})]

    def _close_open(self) -> list[bytes]:
        if self.open is None:
            return []
        index, _ = self.open
        self.open = None
        return [_event("content_block_stop", {"type": "content_block_stop", "index": index})]

    def _open_text(self, kind: str, block_type: str) -> tuple[list[bytes], int]:
        if self.open is not None and self.open[1] == kind:
            return [], self.open[0]
        out = self._close_open()
        index = self.next_index
        self.next_index += 1
        self.open = (index, kind)
        start = {"type": "content_block_start", "index": index, "content_block": {"type": block_type, block_type: ""}}
        return [*out, _event("content_block_start", start)], index

    def chunk(self, c: CanonicalChunk) -> list[bytes]:
        delta = c.delta
        dtype = delta.get("type")
        if dtype == "text":
            out, index = self._open_text("text", "text")
            body = {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": delta.get("text", "")}}
            return [*out, _event("content_block_delta", body)]
        if dtype == "reasoning":
            out, index = self._open_text("thinking", "thinking")
            body = {"type": "content_block_delta", "index": index, "delta": {"type": "thinking_delta", "thinking": delta.get("text", "")}}
            return [*out, _event("content_block_delta", body)]
        if dtype == "tool_call":
            return self._tool_chunk(delta)
        return []

    def _tool_chunk(self, delta: dict[str, Any]) -> list[bytes]:
        canonical_index = delta.get("index", 0)
        fn = delta.get("function") or {}
        if canonical_index not in self.tool_blocks:
            out = self._close_open()
            index = self.next_index
            self.next_index += 1
            self.tool_blocks[canonical_index] = index
            self.open = (index, f"tool:{canonical_index}")
            block = {"type": "tool_use", "id": delta.get("id"), "name": fn.get("name", ""), "input": {}}
            out.append(_event("content_block_start", {"type": "content_block_start", "index": index, "content_block": block}))
            if fn.get("arguments"):
                out.append(_event("content_block_delta", _input_json(index, fn["arguments"])))
            return out
        index = self.tool_blocks[canonical_index]
        if fn.get("arguments"):
            return [_event("content_block_delta", _input_json(index, fn["arguments"]))]
        return []

    def finish(self, final: CanonicalResponse) -> list[bytes]:
        out = self._close_open()
        stop = REVERSE_STOP.get(final.finish_reason or "", "end_turn")
        # Usage is only known at stream end (chunks carry none), so the full breakdown lands here rather than in
        # message_start; a client that reads input/cache solely from message_start cannot see it on a cross-provider stream.
        message_delta = {
            "type": "message_delta",
            "delta": {"stop_reason": stop, "stop_sequence": None},
            "usage": _usage_payload(final.usage),
        }
        out.append(_event("message_delta", message_delta))
        out.append(_event("message_stop", {"type": "message_stop"}))
        return out

    def error(self, err: CanonicalError) -> list[bytes]:
        return [_event("error", {"type": "error", "error": {"type": err.code, "message": err.message}})]


class AnthropicIngress(Ingress):
    """Anthropic's Messages surface at /v1/messages, routed to any provider."""

    def parse(self, body: bytes) -> CanonicalRequest:
        data = json.loads(body)
        messages: list[dict[str, Any]] = []
        system = _system_message(data.get("system"))
        if system:
            messages.append(system)
        messages.extend(_normalize_message(m) for m in data.get("messages", []))
        return CanonicalRequest(
            model=data["model"],
            messages=messages,
            stream=bool(data.get("stream", False)),
            max_tokens=data.get("max_tokens"),
            temperature=data.get("temperature"),
            tools=[_from_anthropic_tool(t) for t in data["tools"]] if data.get("tools") else None,
        )

    def render_response(self, final: CanonicalResponse) -> Response:
        message = {
            "id": final.id,
            "type": "message",
            "role": "assistant",
            "model": final.model,
            "content": _to_anthropic_content(final.content),
            "stop_reason": REVERSE_STOP.get(final.finish_reason or "", "end_turn"),
            "stop_sequence": None,
            "usage": _usage_payload(final.usage),
        }
        return Response(json.dumps(message), media_type="application/json")

    def render_error(self, err: CanonicalError) -> JSONResponse:
        return JSONResponse({"type": "error", "error": {"type": err.code, "message": err.message}}, status_code=err.status)

    def render_upstream_error(self, status_code: int, body: bytes) -> Response:
        try:
            detail = json.loads(body)
            message = detail.get("error", {}).get("message") or detail.get("message") or body.decode(errors="replace")
        except (json.JSONDecodeError, AttributeError):
            message = body.decode(errors="replace")
        payload = {"type": "error", "error": {"type": "upstream_error", "message": message}}
        return Response(json.dumps(payload), status_code=status_code, media_type="application/json")

    def new_egress(self) -> EgressStream:
        return AnthropicEgressStream()
