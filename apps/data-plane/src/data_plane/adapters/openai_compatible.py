"""The OpenAI-compatible provider family: transport assembly and stream state.

The JSON spelling lives in formats/openai.py, shared with the ingress interpretation; this
module owns what is per-provider-call: endpoint, credential, encoding, and the fold that
accumulates a stream for finalize."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from data_plane.adapters.base import ProviderAdapter, RawEvent, StreamState, UpstreamRequest, UpstreamStreamError, encode
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
)
from data_plane.formats.openai import (
    UpstreamChoice,
    UpstreamChunk,
    UpstreamChunkChoice,
    UpstreamCompletion,
    UpstreamUsage,
    body_of,
    finish_reason,
    response_parts,
    usage_of,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from contract import ModelEntry
    from data_plane.adapters.base import Ctx
    from data_plane.canonical import CanonicalRequest


@dataclass
class ToolCallDraft:
    """One tool call accreting across fragments; index-keyed in the state."""

    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class OpenAIStreamState(StreamState):
    ctx: Ctx = field(kw_only=True)
    response_id: str | None = None
    reasoning: list[str] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    tool_drafts: dict[int, ToolCallDraft] = field(default_factory=dict)
    finish: str | None = None
    usage: UpstreamUsage | None = None

    @property
    def chunk_id(self) -> str:
        return self.response_id or self.ctx.request_id


def _fold_choice(state: OpenAIStreamState, choice: UpstreamChunkChoice) -> list[CanonicalChunk]:
    """Deltas out, accumulation in: everything finalize needs folds into the state as it streams."""
    if choice.finish_reason:
        state.finish = choice.finish_reason
    deltas: list[Delta] = []
    if choice.delta.reasoning_content:
        state.reasoning.append(choice.delta.reasoning_content)
        deltas.append(ReasoningDelta(text=choice.delta.reasoning_content))
    if choice.delta.content:
        state.text.append(choice.delta.content)
        deltas.append(TextDelta(text=choice.delta.content))
    for tc in choice.delta.tool_calls or []:
        draft = state.tool_drafts.setdefault(tc.index, ToolCallDraft())
        if tc.id:
            draft.id = tc.id
        if tc.function.name:
            draft.name = tc.function.name
        draft.arguments += tc.function.arguments
        deltas.append(ToolCallDelta(index=tc.index, id=tc.id, name=tc.function.name or None, arguments=tc.function.arguments))
    return [CanonicalChunk(id=state.chunk_id, delta=delta) for delta in deltas]


class OpenAICompatibleAdapter(ProviderAdapter):
    kind = "openai_compatible"

    def transform_request(self, req: CanonicalRequest, m: ModelEntry) -> UpstreamRequest:
        """Transport assembly only; every field mapping lives in formats.openai.body_of."""
        headers = {
            "authorization": f"Bearer {self.credential.reveal()}",
            "content-type": "application/json",
        }
        url = str(self.provider.base_url).rstrip("/") + "/chat/completions"
        return UpstreamRequest(method="POST", url=url, headers=headers, body=encode(body_of(req, m.upstream_model)))

    def transform_response(self, raw: bytes, ctx: Ctx) -> CanonicalResponse:
        completion = UpstreamCompletion.model_validate_json(raw)
        choice = completion.choices[0] if completion.choices else UpstreamChoice()
        return CanonicalResponse(
            id=completion.id or ctx.request_id,
            model=ctx.model.model_id,
            content=response_parts(choice.message),
            finish_reason=finish_reason(choice.finish_reason),
            usage=usage_of(completion.usage),
        )

    def new_stream_state(self, ctx: Ctx) -> OpenAIStreamState:
        return OpenAIStreamState(ctx=ctx)

    def frame(self, chunk: bytes, state: StreamState) -> Iterator[RawEvent]:
        state.buffer += chunk
        *lines, state.buffer = state.buffer.split(b"\n")
        for raw_line in lines:
            line = raw_line.rstrip(b"\r")
            if not line.startswith(b"data:"):
                continue
            data = line[len(b"data:") :].strip()
            if data == b"[DONE]":
                continue
            yield RawEvent(data=data)

    def transform_stream_event(self, ev: RawEvent, state: StreamState) -> list[CanonicalChunk]:
        assert isinstance(state, OpenAIStreamState)  # noqa: S101 state comes from new_stream_state
        data = json.loads(ev.data)
        if "error" in data:
            error = data["error"] or {}
            raise UpstreamStreamError(code=str(error.get("code") or "upstream_error"), message=str(error.get("message") or ""))
        chunk = UpstreamChunk.model_validate(data)
        if chunk.id:
            state.response_id = chunk.id
        if chunk.usage is not None:
            state.usage = chunk.usage
        return [c for choice in chunk.choices for c in _fold_choice(state, choice)]

    def finalize(self, state: StreamState) -> CanonicalResponse:
        assert isinstance(state, OpenAIStreamState)  # noqa: S101 state comes from new_stream_state
        parts: list[AssistantPart] = []
        if reasoning := "".join(state.reasoning):
            parts.append(ReasoningPart(text=reasoning))
        if text := "".join(state.text):
            parts.append(TextPart(text=text))
        parts.extend(ToolCallPart(id=draft.id, name=draft.name, arguments=draft.arguments) for _, draft in sorted(state.tool_drafts.items()))
        return CanonicalResponse(
            id=state.chunk_id,
            model=state.ctx.model.model_id,
            content=parts,
            finish_reason=finish_reason(state.finish),
            usage=usage_of(state.usage),
        )
