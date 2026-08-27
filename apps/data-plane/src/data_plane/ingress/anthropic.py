"""The Anthropic dialect: the Messages surface at /inf/v1/messages, routed to any provider.

Claude Code and the Anthropic SDKs speak this. Requests parse through the same canonical
middle as every other request; replies come back as Anthropic's shapes, buffered and as the
named-event stream. The route binds this dialect directly, so claims() never competes: per the
plan's warning, it must not lean on x-stainless-* headers, which every Stainless-generated SDK
sends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse, Response

from data_plane.canonical import Adjustment, CanonicalChunk, CanonicalRequest, GatewayInfo, ReasoningConfig, ResponseFormat
from data_plane.formats import anthropic as fmt
from data_plane.ingress.base import IngressAdapter

if TYPE_CHECKING:
    from starlette.datastructures import Headers

    from data_plane.canonical import CanonicalResponse
    from data_plane.egress.base import CanonicalError, Ctx

# This dialect's own spellings of canonical fields; everything else rides through as extras,
# so top_k and metadata reach providers whose profile accepts them.
CONSUMED = frozenset(CanonicalRequest.model_fields) | frozenset({"system", "stop_sequences", "thinking", "output_config"})


def _mapping(value: object) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


@dataclass
class _OpenBlock:
    index: int
    key: str  # what the block holds: "text", "thinking", or one tool call


class AnthropicResponseStream:
    """Rebuilds Anthropic's named-event stream from canonical chunks.

    Canonical chunks are a flat sequence with no block boundaries. Anthropic content is a
    numbered sequence of blocks with exactly one open at a time. Every chunk names the block it
    belongs to, so a change of key is the boundary: close the open block, open the next."""

    def __init__(self) -> None:
        self.open: _OpenBlock | None = None
        self.opened = 0  # blocks opened so far, which is also the next index

    def start(self, ctx: Ctx, /) -> list[bytes]:
        message = fmt.MessageStartOut(id=ctx.request_id, model=ctx.model.model_id)
        return [fmt.MessageStart(message=message).sse(), fmt.Ping().sse()]

    def _close(self) -> list[bytes]:
        if self.open is None:
            return []
        block, self.open = self.open, None
        return [fmt.ContentBlockStop(index=block.index).sse()]

    def _switch(self, key: str, opening: fmt.BlockOut) -> tuple[list[bytes], int]:
        """The one boundary rule: same key keeps the open block, a new key ends it and starts the next."""
        if self.open is not None and self.open.key == key:
            return [], self.open.index
        events = self._close()
        self.open = _OpenBlock(index=self.opened, key=key)
        self.opened += 1
        return [*events, fmt.ContentBlockStart(index=self.open.index, content_block=opening).sse()], self.open.index

    def chunk(self, c: CanonicalChunk) -> list[bytes]:
        delta = c.delta
        if delta is None:
            return []
        if delta.type == "text":
            events, index = self._switch("text", fmt.TextOut(text=""))
            return [*events, fmt.ContentBlockDelta(index=index, delta=fmt.TextDeltaOut(text=delta.text)).sse()]
        if delta.type == "reasoning":
            events, index = self._switch("thinking", fmt.ThinkingOut(thinking=""))
            if delta.signature:
                events.append(fmt.ContentBlockDelta(index=index, delta=fmt.SignatureDeltaOut(signature=delta.signature)).sse())
            if delta.text:
                events.append(fmt.ContentBlockDelta(index=index, delta=fmt.ThinkingDeltaOut(thinking=delta.text)).sse())
            return events
        opening = fmt.ToolUseOut(id=delta.id or "", name=delta.name or "", input={})
        events, index = self._switch(f"tool:{delta.index}", opening)
        if delta.arguments:
            events.append(fmt.ContentBlockDelta(index=index, delta=fmt.InputJsonDeltaOut(partial_json=delta.arguments)).sse())
        return events

    def closing(self, final: CanonicalResponse, adjustments: list[Adjustment]) -> list[bytes]:
        # Usage is only known at stream end (canonical chunks carry none), so the full breakdown
        # lands in message_delta rather than message_start; gateway rides there as an extra field.
        stop = fmt.StopDeltaOut(stop_reason=fmt.stop_reason(final.finish_reason))
        delta = fmt.MessageDelta(delta=stop, usage=fmt.usage_out(final.usage), gateway=GatewayInfo(adjustments=adjustments))
        return [*self._close(), delta.sse(), fmt.MessageStop().sse()]

    def error(self, err: CanonicalError) -> list[bytes]:
        return [fmt.ErrorEvent(error=fmt.ErrorOut(type=err.code, message=err.message)).sse()]


class AnthropicIngress(IngressAdapter):
    dialect = "anthropic"

    def claims(self, _headers: Headers, _body: dict[str, Any], /) -> bool:
        """Never claims on the chat route: /inf/v1/messages binds this dialect directly."""
        return False

    def parse(self, body: dict[str, Any]) -> tuple[CanonicalRequest, list[Adjustment]]:
        extras = {key: value for key, value in body.items() if key not in CONSUMED}
        adjustments = []
        raw_tool_choice = body.get("tool_choice")
        tool_choice = fmt.from_tool_choice(raw_tool_choice)
        if body.get("tool_choice") is not None and tool_choice is None:
            adjustments.append(Adjustment(param="tool_choice", action="dropped", detail="a tool_choice variant this dialect does not interpret"))
        thinking = _mapping(body.get("thinking"))
        output_config = _mapping(body.get("output_config"))
        raw_format = output_config.get("format")
        format_value = _mapping(raw_format) if isinstance(raw_format, dict) else None
        response_format = None
        if format_value is not None and format_value.get("type") == "json_schema":
            response_format = ResponseFormat(type="json_schema", json_schema={"schema": format_value.get("schema") or {}})
        reasoning_values = {
            "type": thinking.get("type"),
            "budget_tokens": thinking.get("budget_tokens"),
            "display": thinking.get("display"),
            "effort": output_config.get("effort"),
        }
        reasoning = ReasoningConfig.model_validate(reasoning_values) if any(value is not None for value in reasoning_values.values()) else None
        request = CanonicalRequest.model_validate(
            {
                **extras,
                "model": str(body.get("model") or ""),
                "messages": fmt.from_request(body),
                "stream": bool(body.get("stream") or False),
                "max_tokens": body.get("max_tokens"),
                "temperature": body.get("temperature"),
                "top_p": body.get("top_p"),
                "stop": body.get("stop_sequences"),
                "tools": fmt.from_tools(body.get("tools")),
                "tool_choice": tool_choice,
                "parallel_tool_calls": (
                    not raw_tool_choice["disable_parallel_tool_use"]
                    if isinstance(raw_tool_choice, dict) and isinstance(raw_tool_choice.get("disable_parallel_tool_use"), bool)
                    else None
                ),
                "reasoning": reasoning,
                "response_format": response_format,
            }
        )
        return request, adjustments

    def render_response(self, final: CanonicalResponse) -> Response:
        message = fmt.MessageOut(
            id=final.id,
            model=final.model,
            content=fmt.to_response_content(final.content),
            stop_reason=fmt.stop_reason(final.finish_reason),
            usage=fmt.usage_out(final.usage),
            gateway=final.gateway,
        )
        return Response(message.model_dump_json(exclude_none=True), media_type="application/json")

    def render_error(self, err: CanonicalError) -> Response:
        return JSONResponse({"type": "error", "error": {"type": err.code, "message": err.message}}, status_code=err.status)

    def new_stream(self) -> AnthropicResponseStream:
        return AnthropicResponseStream()
