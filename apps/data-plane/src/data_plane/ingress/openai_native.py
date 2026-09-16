"""OpenAI Chat Completions ingress and streaming responses."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse, Response

from data_plane.canonical import (
    CanonicalAdjustment,
    CanonicalChunk,
    CanonicalGatewayInfo,
    CanonicalReasoningConfig,
    CanonicalRequest,
    CanonicalToolCallDelta,
)
from data_plane.formats import openai as fmt
from data_plane.ingress.base import DONE, IngressAdapter

if TYPE_CHECKING:
    from starlette.datastructures import Headers

    from data_plane.canonical import CanonicalResponse
    from data_plane.egress.base import CanonicalError, Ctx

# This dialect's alternate spellings of canonical fields: parse folds each into its canonical
# name, and the egress side re-spells the canonical value however the provider wants it.
ALIASED = frozenset({"max_tokens", "max_completion_tokens", "reasoning_effort"})

# Protocol plumbing with no canonical carrier because its meaning is constant under our
# contract: the stream always reports usage, and body_of re-emits its own stream_options on
# every streamed upstream request regardless of what the caller sent.
CONSTANT = frozenset({"stream_options"})

# Everything consumed here is spoken for; everything else rides through as canonical extras, so
# the reconcile step reports or forwards it exactly as for a canonical caller. Deriving the core
# from the definition means a field added to canonical is consumed here without an edit.
CONSUMED = (frozenset(CanonicalRequest.model_fields) - {"max_output_tokens"}) | ALIASED | CONSTANT


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
    return "max_tokens" in body or "max_completion_tokens" in body


def _error_body(status: int, code: str, message: str) -> dict[str, dict[str, str]]:
    kind = "invalid_request_error" if status < 500 else "api_error"  # noqa: PLR2004 the HTTP class boundary
    return {"error": {"type": kind, "code": code, "message": message}}


class OpenAIResponseStream:
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

    def start(self, ctx: Ctx, /) -> list[bytes]:
        self.id, self.model, self.created = str(ctx.request_id), ctx.model.model_id, int(time.time())
        return [self._chunk(fmt.DeltaOut(role="assistant"))]

    def chunk(self, c: CanonicalChunk) -> list[bytes]:
        delta = c.delta
        if delta is None:
            return []
        if delta.type == "text":
            return [self._chunk(fmt.DeltaOut(content=delta.text))]
        if delta.type == "reasoning":
            return [self._chunk(fmt.DeltaOut(reasoning_content=delta.text))]
        return [self._chunk(fmt.DeltaOut(tool_calls=[_tool_call_delta(delta)]))]

    def closing(self, final: CanonicalResponse, adjustments: list[CanonicalAdjustment]) -> list[bytes]:
        usage_chunk = fmt.ChatCompletionChunkOut(
            id=self.id,
            created=self.created,
            model=self.model,
            choices=[],
            usage=fmt.usage_out(final.usage),
            gateway=CanonicalGatewayInfo(finish_reason=final.finish_reason, adjustments=adjustments),
        )
        return [self._chunk(fmt.DeltaOut(), finish_reason=final.finish_reason), usage_chunk.sse(), DONE]

    def error(self, err: CanonicalError) -> list[bytes]:
        return [b"data: " + json.dumps(_error_body(err.status, err.code, err.message)).encode() + b"\n\n", DONE]


def _tool_call_delta(delta: CanonicalToolCallDelta) -> fmt.ToolCallDeltaOut:
    function = {**({"name": delta.name} if delta.name else {}), **({"arguments": delta.arguments} if delta.arguments else {})}
    return fmt.ToolCallDeltaOut(index=delta.index, id=delta.id, type="function" if delta.id else None, function=function or None)


class OpenAINativeIngress(IngressAdapter):
    dialect = "openai_native"

    def claims(self, headers: Headers, body: dict[str, Any], /) -> bool:
        """The client fingerprint the official SDKs send on every request, or an unambiguous shape.

        A text-only body is shape-identical in both dialects, which is why the fingerprint matters.
        The User-Agent prefix and not the x-stainless-* family, deliberately: those headers mean
        "a Stainless-generated SDK", which other vendors' clients also are."""
        if headers.get("user-agent", "").startswith("OpenAI/"):
            return True
        return _openai_shaped(body)

    def parse(self, body: dict[str, Any]) -> tuple[CanonicalRequest, list[CanonicalAdjustment]]:
        """An OpenAI chat request into canonical. Unconsumed fields stay extras; stream_options is
        consumed silently because the gateway's own stream always reports usage.

        An unrecognized value in a consumed slot (a tool_choice variant this parse does not
        know) is a translation loss: reported as an adjustment, never a silent None."""
        if "max_output_tokens" in body:
            message = "Chat Completions requests use max_tokens or max_completion_tokens, not max_output_tokens"
            raise ValueError(message)
        if "max_tokens" in body and "max_completion_tokens" in body:
            message = "supply max_tokens or max_completion_tokens, not both"
            raise ValueError(message)
        stop = body.get("stop")
        extras = {key: value for key, value in body.items() if key not in CONSUMED}
        adjustments = []
        tool_choice = fmt.from_tool_choice(body.get("tool_choice"))
        if body.get("tool_choice") is not None and tool_choice is None:
            adjustments.append(
                CanonicalAdjustment(param="tool_choice", action="dropped", detail="a tool_choice variant this dialect does not interpret")
            )
        response_format = body.get("response_format")
        reasoning_value = body.get("reasoning")
        if reasoning_value is not None and not isinstance(reasoning_value, dict):
            message = "reasoning must be a JSON object"
            raise ValueError(message)
        reasoning = reasoning_value or {}
        reasoning_values = {
            "type": reasoning.get("type"),
            "effort": reasoning.get("effort") or body.get("reasoning_effort"),
            "summary": reasoning.get("summary"),
            "budget_tokens": reasoning.get("budget_tokens"),
            "display": reasoning.get("display"),
        }
        has_reasoning = bool(reasoning) or isinstance(body.get("reasoning_effort"), str)
        request = CanonicalRequest.model_validate(
            {
                **extras,
                "model": body.get("model"),
                "messages": fmt.from_messages(body.get("messages")),
                "stream": body.get("stream", False),
                "max_output_tokens": body.get("max_completion_tokens", body.get("max_tokens")),
                "temperature": body.get("temperature"),
                "top_p": body.get("top_p"),
                "stop": [stop] if isinstance(stop, str) else stop,
                "seed": body.get("seed"),
                "tools": fmt.from_tools(body.get("tools")),
                "tool_choice": tool_choice,
                "response_format": response_format,
                "reasoning": CanonicalReasoningConfig.model_validate(reasoning_values) if has_reasoning else None,
                "parallel_tool_calls": body.get("parallel_tool_calls"),
            }
        )
        return request, adjustments

    def render_response(self, final: CanonicalResponse) -> Response:
        choice = fmt.ChoiceOut(message=fmt.to_message(final.content), finish_reason=final.finish_reason)
        completion = fmt.ChatCompletionOut(
            id=final.id, created=int(time.time()), model=final.model, choices=[choice], usage=fmt.usage_out(final.usage), gateway=final.gateway
        )
        return Response(completion.model_dump_json(exclude_none=True), media_type="application/json")

    def render_error(self, err: CanonicalError) -> Response:
        return JSONResponse(_error_body(err.status, err.code, err.message), status_code=err.status)

    def new_stream(self) -> OpenAIResponseStream:
        return OpenAIResponseStream()
