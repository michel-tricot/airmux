"""OpenAI Responses egress adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import ValidationError

from data_plane.canonical import (
    CanonicalChunk,
    CanonicalReasoningDelta,
    CanonicalReasoningPart,
    CanonicalResponse,
    CanonicalTextDelta,
    CanonicalTextPart,
    CanonicalToolCallDelta,
    CanonicalToolCallPart,
)
from data_plane.egress.base import (
    CanonicalError,
    EgressAdapter,
    RawEvent,
    StreamState,
    UpstreamProtocolError,
    UpstreamRequest,
    UpstreamResponseError,
    UpstreamStreamError,
    encode,
    frame_sse,
)
from data_plane.formats import openai_responses as fmt

if TYPE_CHECKING:
    from collections.abc import Iterator

    from contract import ModelEntry
    from data_plane.canonical import CanonicalRequest
    from data_plane.egress.base import Ctx


@dataclass
class ResponsesOutputDraft:
    type: str = ""
    id: str = ""
    name: str = ""
    arguments: str = ""
    ordinal: int | None = None


@dataclass
class ResponsesReasoningDraft:
    id: str = ""
    text: str = ""
    signature: str = ""


@dataclass
class ResponsesStreamState(StreamState):
    ctx: Ctx = field(kw_only=True)
    response_id: str | None = None
    output: dict[int, ResponsesOutputDraft] = field(default_factory=dict)
    reasoning: dict[int, ResponsesReasoningDraft] = field(default_factory=dict)
    text: dict[int, str] = field(default_factory=dict)
    usage: dict[str, object] | None = None
    tool_count: int = 0
    terminal_seen: bool = False
    incomplete: bool = False

    @property
    def chunk_id(self) -> str:
        return self.response_id or str(self.ctx.request_id)


def _error(error: fmt.UpstreamError | None) -> UpstreamStreamError | None:
    if error is None:
        return None
    return UpstreamStreamError(error.code or "upstream_error", error.message)


def _tool_draft(state: ResponsesStreamState, index: int) -> ResponsesOutputDraft:
    draft = state.output.setdefault(index, ResponsesOutputDraft(type="function_call"))
    if draft.ordinal is None:
        draft.ordinal = state.tool_count
        state.tool_count += 1
    return draft


class OpenAIResponsesAdapter(EgressAdapter[ResponsesStreamState]):
    kind = "openai_responses"

    def transform_request(self, req: CanonicalRequest, m: ModelEntry) -> UpstreamRequest:
        body = fmt.body_of(req, m.upstream_model)
        return UpstreamRequest(
            method="POST",
            url=str(self.provider.base_url).rstrip("/") + "/responses",
            headers={"authorization": f"Bearer {self.credential.reveal()}", "content-type": "application/json"},
            body=encode(body, aliases=self.provider.param_aliases, extras=req.extra),
        )

    def transform_response(self, raw: bytes, ctx: Ctx) -> CanonicalResponse:
        try:
            parsed = fmt.UpstreamResponse.model_validate_json(raw)
        except ValidationError as error:
            raise UpstreamProtocolError.buffered_response() from error
        if parsed.status == "failed" or parsed.error is not None:
            raise UpstreamProtocolError.buffered_response()
        response = parsed.model_dump(mode="json", exclude_none=True)
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
            detail = fmt.UpstreamResponseEvent.model_validate_json(error.body).error
        except ValidationError:
            return super().map_error(error)
        if detail is None:
            return super().map_error(error)
        return CanonicalError(status=error.status, code=detail.code or "upstream_error", message=detail.message)

    def new_stream_state(self, ctx: Ctx) -> ResponsesStreamState:
        return ResponsesStreamState(ctx=ctx)

    def frame(self, chunk: bytes, state: ResponsesStreamState) -> Iterator[RawEvent]:
        if not state.terminal_seen:
            yield from frame_sse(chunk, state)

    def transform_stream_event(self, ev: RawEvent, state: ResponsesStreamState) -> list[CanonicalChunk]:  # noqa: PLR0911, PLR0912 - event lifecycle branches are explicit
        try:
            event = fmt.UpstreamResponseEvent.model_validate_json(ev.data)
        except ValidationError as error:
            raise UpstreamProtocolError.stream_event() from error
        response_error = event.response.error if event.response is not None else None
        if error := _error(event.error or response_error):
            raise error
        kind = event.type or ev.name
        if event.response is not None:
            state.response_id = event.response.id or state.response_id
            if event.response.usage is not None:
                state.usage = event.response.usage
        if kind in {"response.completed", "response.incomplete"}:
            state.terminal_seen = True
            state.incomplete = kind == "response.incomplete"
            return []
        if kind == "response.failed":
            code, message = "upstream_error", "response failed"
            raise UpstreamStreamError(code, message)
        if kind == "error":
            code, message = "upstream_error", "response failed"
            raise UpstreamStreamError(code, message)
        index = event.output_index
        if index is None:
            return []
        if kind == "response.output_item.added":
            item = event.item
            if item is not None:
                if item.type == "reasoning":
                    state.reasoning[index] = ResponsesReasoningDraft(
                        id=item.id,
                        signature=item.encrypted_content,
                    )
                    reasoning = state.reasoning[index]
                    return [
                        CanonicalChunk(
                            id=state.chunk_id,
                            delta=CanonicalReasoningDelta(id=reasoning.id or None, signature=reasoning.signature or None),
                        )
                    ]
                if item.type == "function_call":
                    output = _tool_draft(state, index)
                    output.id = item.call_id
                    output.name = item.name
                    output.arguments = item.arguments
                    return [
                        CanonicalChunk(
                            id=state.chunk_id,
                            delta=CanonicalToolCallDelta(index=output.ordinal or 0, id=output.id or None, name=output.name or None),
                        )
                    ]
                state.output[index] = ResponsesOutputDraft(type=item.type)
            return []
        if kind == "response.output_text.delta":
            delta = event.delta
            state.text[index] = state.text.get(index, "") + delta
            return [CanonicalChunk(id=state.chunk_id, delta=CanonicalTextDelta(text=delta))] if delta else []
        if kind in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
            delta = event.delta
            draft = state.reasoning.setdefault(index, ResponsesReasoningDraft())
            draft.text += delta
            return [CanonicalChunk(id=state.chunk_id, delta=CanonicalReasoningDelta(text=delta))] if delta else []
        if kind == "response.function_call_arguments.delta":
            delta = event.delta
            draft = _tool_draft(state, index)
            draft.arguments += delta
            return [CanonicalChunk(id=state.chunk_id, delta=CanonicalToolCallDelta(index=draft.ordinal or 0, arguments=delta))] if delta else []
        return []

    def validate_stream(self, state: ResponsesStreamState) -> None:
        if not state.terminal_seen:
            raise UpstreamProtocolError.incomplete_stream()

    def finalize(self, state: ResponsesStreamState) -> CanonicalResponse:
        parts = []
        for index in sorted(set(state.output) | set(state.text) | set(state.reasoning)):
            if index in state.reasoning:
                draft = state.reasoning[index]
                parts.append(CanonicalReasoningPart(id=draft.id or None, text=draft.text, signature=draft.signature or None))
            if text := state.text.get(index):
                parts.append(CanonicalTextPart(text=text))
            output = state.output.get(index)
            if output and output.type == "function_call":
                parts.append(CanonicalToolCallPart(id=output.id, name=output.name, arguments=output.arguments))
        finish = (
            "length"
            if state.incomplete
            else ("tool_calls" if any(isinstance(part, CanonicalToolCallPart) for part in parts) else ("stop" if state.terminal_seen else None))
        )
        return CanonicalResponse(
            id=state.chunk_id, model=state.ctx.model.model_id, content=parts, finish_reason=finish, usage=fmt.usage_of(state.usage)
        )
