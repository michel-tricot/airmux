"""OpenAI interpretation on the native route, per INTERFACE.md.

An unmodified OpenAI client that swapped only its base URL is recognized here and answered in
the shape it spoke: choices on the completion, OpenAI chunk objects on the stream, [DONE] at
the end. Everything in between runs through the same canonical middle as every other request,
and a canonical caller never sees any of this: detection cannot change a canonical answer."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from starlette.responses import Response

from data_plane.canonical import (
    CanonicalChunk,
    CanonicalRequest,
    GatewayInfo,
    ResponseFormat,
    ToolCallDelta,
)
from data_plane.formats import openai as fmt

if TYPE_CHECKING:
    from starlette.datastructures import Headers

    from data_plane.canonical import Adjustment, CanonicalResponse
    from data_plane.egress.base import CanonicalError, Ctx

DIALECT_HEADER = "x-airllm-dialect"

# Body keys the interpretation consumes; everything else rides through as canonical extras, so
# the reconcile step reports or forwards them exactly as it does for a canonical caller.
CONSUMED = frozenset(
    {"model", "messages", "stream", "max_tokens", "max_completion_tokens", "temperature", "top_p", "stop", "seed"}
    | {"tools", "tool_choice", "response_format", "stream_options"}
)

DONE = b"data: [DONE]\n\n"


def wants_openai(headers: Headers, body: dict[str, Any]) -> bool:
    """Explicit override first, then the client fingerprint, then unambiguous body shapes.

    A text-only body is shape-identical in both dialects, which is why the fingerprint matters:
    the official SDKs announce themselves on every request."""
    override = headers.get(DIALECT_HEADER, "").lower()
    if override in {"openai", "canonical"}:
        return override == "openai"
    if any(name.lower().startswith("x-stainless-") for name in headers) or headers.get("user-agent", "").startswith("OpenAI/"):
        return True
    return _openai_shaped(body)


def _openai_shaped(body: dict[str, Any]) -> bool:
    messages = body.get("messages")
    for raw in messages if isinstance(messages, list) else []:
        message = raw if isinstance(raw, dict) else {}
        if message.get("role") in {"tool", "developer"} or "tool_calls" in message:
            return True
        content = message.get("content")
        if isinstance(content, list) and any(isinstance(block, dict) and block.get("type") == "image_url" for block in content):
            return True
    tools = body.get("tools")
    if isinstance(tools, list) and any(isinstance(tool, dict) and "function" in tool for tool in tools):
        return True
    if isinstance(body.get("tool_choice"), dict) and "function" in body["tool_choice"]:
        return True
    return "max_completion_tokens" in body


def parse(body: dict[str, Any]) -> CanonicalRequest:
    """An OpenAI chat request into canonical. Unconsumed fields stay extras; stream_options is
    consumed silently because the gateway's own stream always reports usage."""
    stop = body.get("stop")
    extras = {key: value for key, value in body.items() if key not in CONSUMED}
    response_format = body.get("response_format")
    return CanonicalRequest.model_validate(
        {
            **extras,
            "model": body.get("model") or "",
            "messages": fmt.from_messages(body.get("messages")),
            "stream": bool(body.get("stream") or False),
            "max_tokens": body.get("max_tokens") or body.get("max_completion_tokens"),
            "temperature": body.get("temperature"),
            "top_p": body.get("top_p"),
            "stop": [stop] if isinstance(stop, str) else stop,
            "seed": body.get("seed"),
            "tools": fmt.from_tools(body.get("tools")),
            "tool_choice": fmt.from_tool_choice(body.get("tool_choice")),
            "response_format": ResponseFormat.model_validate(response_format) if response_format else None,
        }
    )


def render_response(final: CanonicalResponse) -> Response:
    choice = fmt.ChoiceOut(message=fmt.to_message(final.content), finish_reason=final.finish_reason)
    completion = fmt.ChatCompletionOut(
        id=final.id, created=int(time.time()), model=final.model, choices=[choice], usage=fmt.usage_out(final.usage), gateway=final.gateway
    )
    return Response(completion.model_dump_json(exclude_none=True), media_type="application/json")


class OpenAIEgress:
    """Renders the canonical stream as OpenAI chunk objects.

    Every chunk repeats id, model and created because each one is a standalone object in
    OpenAI's protocol; the usage-bearing final chunk carries no choices, which is how
    stream_options.include_usage reports it, and gateway rides along there."""

    def __init__(self) -> None:
        self.id = ""
        self.model = ""
        self.created = 0

    def _chunk(self, delta: fmt.DeltaOut, finish_reason: str | None = None) -> bytes:
        choice = fmt.ChunkChoiceOut(delta=delta, finish_reason=finish_reason)
        return fmt.ChatCompletionChunkOut(id=self.id, created=self.created, model=self.model, choices=[choice]).sse()

    def start(self, ctx: Ctx) -> list[bytes]:
        self.id, self.model, self.created = ctx.request_id, ctx.model.model_id, int(time.time())
        return [self._chunk(fmt.DeltaOut(role="assistant"))]

    def chunk(self, c: CanonicalChunk) -> list[bytes]:
        if c.delta is None:
            return []
        if c.delta.type == "text":
            return [self._chunk(fmt.DeltaOut(content=c.delta.text))]
        if c.delta.type == "reasoning":
            return [self._chunk(fmt.DeltaOut(reasoning_content=c.delta.text))] if c.delta.text else []
        return [self._chunk(fmt.DeltaOut(tool_calls=[_tool_call_delta(c.delta)]))]

    def closing(self, final: CanonicalResponse, adjustments: list[Adjustment]) -> list[bytes]:
        usage_chunk = fmt.ChatCompletionChunkOut(
            id=self.id,
            created=self.created,
            model=self.model,
            choices=[],
            usage=fmt.usage_out(final.usage),
            gateway=GatewayInfo(adjustments=adjustments),
        )
        return [self._chunk(fmt.DeltaOut(), finish_reason=final.finish_reason), usage_chunk.sse(), DONE]

    def error(self, err: CanonicalError) -> list[bytes]:
        body = {"error": {"type": "upstream_error", "code": err.code, "message": err.message}}
        return [b"data: " + json.dumps(body).encode() + b"\n\n", DONE]


def _tool_call_delta(delta: ToolCallDelta) -> fmt.ToolCallDeltaOut:
    function = {**({"name": delta.name} if delta.name else {}), **({"arguments": delta.arguments} if delta.arguments else {})}
    return fmt.ToolCallDeltaOut(index=delta.index, id=delta.id, type="function" if delta.id else None, function=function or None)
