"""Anthropic Messages ingress and streaming responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from data_plane.canonical import CanonicalAdjustment, CanonicalChunk, CanonicalGatewayInfo, CanonicalReasoningConfig, CanonicalRequest
from data_plane.formats import anthropic as fmt
from data_plane.ingress.base import IngressAdapter
from data_plane.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.responses import Response

    from data_plane.canonical import CanonicalError, CanonicalResponse
    from data_plane.egress.base import Ctx

# This dialect's own spellings of canonical fields; everything else rides through as extras,
# so top_k and metadata reach providers whose profile accepts them.
CONSUMED = (frozenset(CanonicalRequest.model_fields) - {"max_output_tokens"}) | frozenset(
    {"max_tokens", "system", "stop_sequences", "thinking", "output_config"}
)


def _mapping(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        message = "expected a JSON object"
        raise TypeError(message)
    if any(not isinstance(key, str) for key in value):
        message = "JSON object keys must be strings"
        raise TypeError(message)
    return cast("dict[str, Any]", value)


@dataclass
class _OpenBlock:
    index: int
    key: str  # what the block holds: "text", "thinking", or one tool call
    reasoning_id: str | None = None
    signature: str = ""


class AnthropicResponseStream:
    """Rebuilds Anthropic's named-event stream from canonical chunks.

    Canonical chunks are a flat sequence with no block boundaries. Anthropic content is a
    numbered sequence of blocks with exactly one open at a time. Every chunk names the block it
    belongs to, so a change of key is the boundary: close the open block, open the next."""

    def __init__(self) -> None:
        self.open: _OpenBlock | None = None
        self.opened = 0  # blocks opened so far, which is also the next index

    def start(self, ctx: Ctx, /) -> list[bytes]:
        message = fmt.MessageStartOut(id=str(ctx.request_id), model=ctx.model.model_id)
        return [fmt.MessageStart(message=message).sse(), fmt.Ping().sse()]

    def _close(self) -> list[bytes]:
        if self.open is None:
            return []
        block, self.open = self.open, None
        events = []
        if block.key == "thinking" and (block.reasoning_id is not None or block.signature):
            signature = fmt.reasoning_signature(block.reasoning_id, block.signature or None)
            events.append(fmt.ContentBlockDelta(index=block.index, delta=fmt.SignatureDeltaOut(signature=signature)).sse())
        return [*events, fmt.ContentBlockStop(index=block.index).sse()]

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
            if self.open is not None:
                self.open.reasoning_id = delta.id or self.open.reasoning_id
                self.open.signature += delta.signature or ""
            if delta.text:
                events.append(fmt.ContentBlockDelta(index=index, delta=fmt.ThinkingDeltaOut(thinking=delta.text)).sse())
            return events
        opening = fmt.ToolUseOut(id=delta.id or "", name=delta.name or "", input={})
        events, index = self._switch(f"tool:{delta.index}", opening)
        if delta.arguments:
            events.append(fmt.ContentBlockDelta(index=index, delta=fmt.InputJsonDeltaOut(partial_json=delta.arguments)).sse())
        return events

    def closing(self, final: CanonicalResponse, adjustments: list[CanonicalAdjustment]) -> list[bytes]:
        # CanonicalUsage is only known at stream end (canonical chunks carry none), so the full breakdown
        # lands in message_delta rather than message_start; gateway rides there as an extra field.
        stop = fmt.StopDeltaOut(stop_reason=fmt.stop_reason(final.finish_reason))
        delta = fmt.MessageDelta(
            delta=stop,
            usage=fmt.usage_out(final.usage),
            gateway=CanonicalGatewayInfo(finish_reason=final.finish_reason, adjustments=adjustments),
        )
        return [*self._close(), delta.sse(), fmt.MessageStop().sse()]

    def error(self, err: CanonicalError) -> list[bytes]:
        return [fmt.ErrorEvent(error=fmt.ErrorOut(type=err.code, message=err.message)).sse()]


class AnthropicIngress(IngressAdapter):
    dialect = "anthropic"
    path = "/inf/v1/messages"

    def parse(self, body: dict[str, Any]) -> tuple[CanonicalRequest, list[CanonicalAdjustment]]:
        if "max_output_tokens" in body:
            message = "Anthropic Messages requests use max_tokens, not max_output_tokens"
            raise ValueError(message)
        if body.get("max_tokens") is None:
            message = "max_tokens is required and must be an integer"
            raise ValueError(message)
        extras = {key: value for key, value in body.items() if key not in CONSUMED}
        adjustments = []
        raw_tool_choice = body.get("tool_choice")
        tool_choice = fmt.from_tool_choice(raw_tool_choice)
        if body.get("tool_choice") is not None and tool_choice is None:
            adjustments.append(
                CanonicalAdjustment(param="tool_choice", action="dropped", detail="a tool_choice variant this dialect does not interpret")
            )
        thinking = _mapping(body.get("thinking"))
        output_config = _mapping(body.get("output_config"))
        reasoning_values = {
            "type": thinking.get("type"),
            "budget_tokens": thinking.get("budget_tokens"),
            "display": thinking.get("display"),
            "effort": output_config.get("effort"),
        }
        reasoning = (
            CanonicalReasoningConfig.model_validate(reasoning_values) if any(value is not None for value in reasoning_values.values()) else None
        )
        request = CanonicalRequest.model_validate(
            {
                **extras,
                "model": body.get("model"),
                "messages": fmt.from_request(body),
                "stream": body.get("stream", False),
                "max_output_tokens": body.get("max_tokens"),
                "temperature": body.get("temperature"),
                "top_p": body.get("top_p"),
                "stop": body.get("stop_sequences"),
                "tools": fmt.from_tools(body.get("tools")),
                "tool_choice": tool_choice,
                "parallel_tool_calls": (
                    not raw_tool_choice["disable_parallel_tool_use"]
                    if isinstance(raw_tool_choice, dict) and raw_tool_choice.get("disable_parallel_tool_use") is not None
                    else body.get("parallel_tool_calls")
                ),
                "reasoning": reasoning,
                "response_format": fmt.response_format_from(output_config),
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
        return JSONResponse(message, exclude_none=True)

    def render_error(self, err: CanonicalError) -> Response:
        return JSONResponse({"type": "error", "error": {"type": err.code, "message": err.message}}, status_code=err.status)

    def new_stream(self) -> AnthropicResponseStream:
        return AnthropicResponseStream()
