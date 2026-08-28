"""OpenAI Responses egress adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from data_plane.canonical import CanonicalChunk, CanonicalResponse, ReasoningDelta, ReasoningPart, TextDelta, TextPart, ToolCallDelta, ToolCallPart
from data_plane.egress.base import (
    CanonicalError,
    EgressAdapter,
    RawEvent,
    StreamState,
    UpstreamProtocolError,
    UpstreamRequest,
    UpstreamResponseError,
    UpstreamStreamError,
    frame_sse,
)
from data_plane.formats import openai_responses as fmt

if TYPE_CHECKING:
    from collections.abc import Iterator

    from contract import ModelEntry
    from data_plane.canonical import CanonicalRequest
    from data_plane.egress.base import Ctx


@dataclass
class ResponsesStreamState(StreamState):
    ctx: Ctx = field(kw_only=True)
    response_id: str | None = None
    output: dict[int, dict[str, str]] = field(default_factory=dict)
    reasoning: dict[int, dict[str, str]] = field(default_factory=dict)
    text: dict[int, str] = field(default_factory=dict)
    usage: object = None
    terminal_seen: bool = False
    incomplete: bool = False

    @property
    def chunk_id(self) -> str:
        return self.response_id or self.ctx.request_id


def _error(data: dict) -> UpstreamStreamError | None:
    error = data.get("error")
    if not isinstance(error, dict):
        return None
    return UpstreamStreamError(str(error.get("code") or "upstream_error"), str(error.get("message") or ""))


class OpenAIResponsesAdapter(EgressAdapter):
    kind = "openai_responses"

    def transform_request(self, req: CanonicalRequest, m: ModelEntry) -> UpstreamRequest:
        body = fmt.body_of(req, m.upstream_model)
        return UpstreamRequest(
            method="POST",
            url=str(self.provider.base_url).rstrip("/") + "/responses",
            headers={"authorization": f"Bearer {self.credential.reveal()}", "content-type": "application/json"},
            body=json.dumps(body).encode(),
        )

    def transform_response(self, raw: bytes, ctx: Ctx) -> CanonicalResponse:
        try:
            response = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise UpstreamProtocolError.buffered_response() from error
        if not isinstance(response, dict):
            raise UpstreamProtocolError.buffered_response()
        if not isinstance(response.get("output"), list):
            raise UpstreamProtocolError.buffered_response()
        parts = fmt.response_parts(response)
        return CanonicalResponse(
            id=str(response.get("id") or ctx.request_id),
            model=ctx.model.model_id,
            content=parts,
            finish_reason=fmt.finish_reason(response, parts),
            usage=fmt.usage_of(response.get("usage")),
        )

    def map_error(self, error: Exception) -> CanonicalError:
        if not isinstance(error, UpstreamResponseError):
            return super().map_error(error)
        try:
            data = json.loads(error.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return super().map_error(error)
        detail = data.get("error") if isinstance(data, dict) else None
        if not isinstance(detail, dict):
            return super().map_error(error)
        return CanonicalError(status=error.status, code=str(detail.get("code") or "upstream_error"), message=str(detail.get("message") or ""))

    def new_stream_state(self, ctx: Ctx) -> ResponsesStreamState:
        return ResponsesStreamState(ctx=ctx)

    def frame(self, chunk: bytes, state: StreamState) -> Iterator[RawEvent]:
        assert isinstance(state, ResponsesStreamState)  # noqa: S101 state comes from new_stream_state
        if not state.terminal_seen:
            yield from frame_sse(chunk, state)

    def transform_stream_event(self, ev: RawEvent, state: StreamState) -> list[CanonicalChunk]:  # noqa: PLR0911, PLR0912 - event lifecycle branches are explicit
        assert isinstance(state, ResponsesStreamState)  # noqa: S101 state comes from new_stream_state
        try:
            data = json.loads(ev.data)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise UpstreamProtocolError.stream_event() from error
        if not isinstance(data, dict):
            raise UpstreamProtocolError.stream_event()
        if error := _error(data):
            raise error
        kind = data.get("type") or ev.name
        response = data.get("response")
        if isinstance(response, dict):
            state.response_id = str(response.get("id") or state.response_id or "") or None
            if "usage" in response:
                state.usage = response["usage"]
        if kind in {"response.completed", "response.incomplete"}:
            state.terminal_seen = True
            state.incomplete = kind == "response.incomplete"
            return []
        if kind in {"response.failed", "error"}:
            code, message = "upstream_error", "response failed"
            raise UpstreamStreamError(code, message)
        index = data.get("output_index")
        if not isinstance(index, int):
            return []
        if kind == "response.output_item.added":
            item = data.get("item")
            if isinstance(item, dict):
                state.output[index] = {
                    "type": str(item.get("type") or ""),
                    "id": str(item.get("call_id") or ""),
                    "name": str(item.get("name") or ""),
                    "arguments": str(item.get("arguments") or ""),
                }
                if item.get("type") == "reasoning":
                    state.reasoning[index] = {
                        "id": str(item.get("id") or ""),
                        "text": "",
                        "signature": str(item.get("encrypted_content") or ""),
                    }
                    reasoning = state.reasoning[index]
                    return [
                        CanonicalChunk(
                            id=state.chunk_id,
                            delta=ReasoningDelta(id=reasoning["id"] or None, signature=reasoning["signature"] or None),
                        )
                    ]
                if item.get("type") == "function_call":
                    output = state.output[index]
                    return [
                        CanonicalChunk(
                            id=state.chunk_id,
                            delta=ToolCallDelta(index=index, id=output["id"] or None, name=output["name"] or None),
                        )
                    ]
            return []
        if kind == "response.output_text.delta":
            delta = str(data.get("delta") or "")
            state.text[index] = state.text.get(index, "") + delta
            return [CanonicalChunk(id=state.chunk_id, delta=TextDelta(text=delta))] if delta else []
        if kind in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
            delta = str(data.get("delta") or "")
            draft = state.reasoning.setdefault(index, {"id": "", "text": "", "signature": ""})
            draft["text"] += delta
            return [CanonicalChunk(id=state.chunk_id, delta=ReasoningDelta(text=delta))] if delta else []
        if kind == "response.function_call_arguments.delta":
            delta = str(data.get("delta") or "")
            draft = state.output.setdefault(index, {"type": "function_call", "id": "", "name": "", "arguments": ""})
            draft["arguments"] += delta
            return [CanonicalChunk(id=state.chunk_id, delta=ToolCallDelta(index=index, arguments=delta))] if delta else []
        return []

    def validate_stream(self, state: StreamState) -> None:
        assert isinstance(state, ResponsesStreamState)  # noqa: S101 state comes from new_stream_state
        if not state.terminal_seen:
            raise UpstreamProtocolError.incomplete_stream()

    def finalize(self, state: StreamState) -> CanonicalResponse:
        assert isinstance(state, ResponsesStreamState)  # noqa: S101 state comes from new_stream_state
        parts = []
        for index in sorted(set(state.output) | set(state.text) | set(state.reasoning)):
            if index in state.reasoning:
                draft = state.reasoning[index]
                parts.append(ReasoningPart(id=draft["id"] or None, text=draft["text"], signature=draft["signature"] or None))
            if text := state.text.get(index):
                parts.append(TextPart(text=text))
            output = state.output.get(index)
            if output and output["type"] == "function_call":
                parts.append(ToolCallPart(id=output["id"], name=output["name"], arguments=output["arguments"]))
        finish = (
            "length"
            if state.incomplete
            else ("tool_calls" if any(isinstance(part, ToolCallPart) for part in parts) else ("stop" if state.terminal_seen else None))
        )
        return CanonicalResponse(
            id=state.chunk_id, model=state.ctx.model.model_id, content=parts, finish_reason=finish, usage=fmt.usage_of(state.usage)
        )
