from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from data_plane.adapters.base import ProviderAdapter
from data_plane.adapters.shape import content_blocks
from data_plane.canonical import CanonicalChunk, CanonicalError, CanonicalResponse, RawEvent, StreamState, UpstreamRequest, UpstreamStreamError, Usage
from data_plane.secrets import resolve

if TYPE_CHECKING:
    from collections.abc import Iterator

    from contract import ModelEntry, ProviderEntry
    from data_plane.canonical import CanonicalRequest, Ctx


@dataclass
class OpenAIStreamState(StreamState):
    ctx: Ctx = field(kw_only=True)
    response_id: str | None = None
    reasoning: list[str] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    tool_calls: dict[int, dict[str, Any]] = field(default_factory=dict)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None

    @property
    def chunk_id(self) -> str:
        return self.response_id or self.ctx.request_id


def _strip_cache_control(obj: object) -> object:
    """OpenAI rejects Anthropic cache markers; it caches automatically, so drop them recursively."""
    if isinstance(obj, dict):
        return {k: _strip_cache_control(v) for k, v in obj.items() if k != "cache_control"}
    if isinstance(obj, list):
        return [_strip_cache_control(v) for v in obj]
    return obj


def _usage(reported: dict[str, Any] | None) -> Usage:
    reported = reported or {}
    return Usage(
        input_tokens=reported.get("prompt_tokens", 0),
        output_tokens=reported.get("completion_tokens", 0),
        estimated=not reported,
    )


def _fold_tool_call(state: OpenAIStreamState, tc: dict[str, Any]) -> dict[str, Any]:
    index = tc.get("index", 0)
    slot = state.tool_calls.setdefault(index, {"id": None, "function": {"name": "", "arguments": ""}})
    if tc.get("id"):
        slot["id"] = tc["id"]
    fn = tc.get("function") or {}
    if fn.get("name"):
        slot["function"]["name"] = fn["name"]
    if fn.get("arguments"):
        slot["function"]["arguments"] += fn["arguments"]
    return {"type": "tool_call", "index": index, "id": tc.get("id"), "function": fn}


def _fold_choice(state: OpenAIStreamState, choice: dict[str, Any]) -> list[CanonicalChunk]:
    delta = choice.get("delta") or {}
    finish = choice.get("finish_reason")
    if finish:
        state.finish_reason = finish
    chunks: list[CanonicalChunk] = []
    if reasoning := delta.get("reasoning_content"):
        state.reasoning.append(reasoning)
        chunks.append(CanonicalChunk(id=state.chunk_id, delta={"type": "reasoning", "text": reasoning}, finish_reason=finish))
    if content := delta.get("content"):
        state.text.append(content)
        chunks.append(CanonicalChunk(id=state.chunk_id, delta={"type": "text", "text": content}, finish_reason=finish))
    chunks.extend(CanonicalChunk(id=state.chunk_id, delta=_fold_tool_call(state, tc), finish_reason=finish) for tc in delta.get("tool_calls") or [])
    if finish and not chunks:
        chunks.append(CanonicalChunk(id=state.chunk_id, delta={}, finish_reason=finish))
    return chunks


class OpenAICompatibleAdapter(ProviderAdapter):
    kind = "openai_compatible"

    def validate_environment(self, p: ProviderEntry) -> None:
        resolve(p.credential_ref)

    def transform_request(self, req: CanonicalRequest, m: ModelEntry) -> UpstreamRequest:
        tools = [_strip_cache_control(t) for t in req.tools] if req.tools else None
        optional = {"max_tokens": req.max_tokens, "temperature": req.temperature, "tools": tools}
        stream_fields: dict[str, Any] = {"stream": True, "stream_options": {"include_usage": True}} if req.stream else {}
        body = {
            "model": m.upstream_model,
            "messages": [_strip_cache_control(msg) for msg in req.messages],
            **{k: v for k, v in optional.items() if v is not None},
            **stream_fields,
        }
        headers = {
            "authorization": f"Bearer {resolve(self.provider.credential_ref)}",
            "content-type": "application/json",
        }
        url = str(self.provider.base_url).rstrip("/") + "/chat/completions"
        return UpstreamRequest(method="POST", url=url, headers=headers, body=json.dumps(body).encode("utf-8"))

    def transform_response(self, raw: bytes, ctx: Ctx) -> CanonicalResponse:
        data = json.loads(raw)
        choice = data["choices"][0]
        message = choice["message"]
        return CanonicalResponse(
            id=data.get("id", ctx.request_id),
            model=ctx.model.model_id,
            content=content_blocks(message.get("reasoning_content") or "", message.get("content") or "", message.get("tool_calls") or []),
            finish_reason=choice.get("finish_reason"),
            usage=_usage(data.get("usage")),
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
        if data.get("id"):
            state.response_id = data["id"]
        if data.get("usage"):
            state.usage = data["usage"]
        chunks: list[CanonicalChunk] = []
        for choice in data.get("choices") or []:
            chunks.extend(_fold_choice(state, choice))
        return chunks

    def finalize(self, state: StreamState) -> CanonicalResponse:
        """Return a valid CanonicalResponse at ANY point in the stream.

        Called after the last event for a normal completion, and from the
        cancellation handler for partial accounting after a client disconnect.
        """
        assert isinstance(state, OpenAIStreamState)  # noqa: S101 state comes from new_stream_state
        return CanonicalResponse(
            id=state.chunk_id,
            model=state.ctx.model.model_id,
            content=content_blocks("".join(state.reasoning), "".join(state.text), [state.tool_calls[i] for i in sorted(state.tool_calls)]),
            finish_reason=state.finish_reason,
            usage=_usage(state.usage),
        )

    def map_error(self, e: Exception) -> CanonicalError:
        if isinstance(e, UpstreamStreamError):
            return CanonicalError(status=502, code=e.code, message=e.message)
        if isinstance(e, httpx.TimeoutException):
            return CanonicalError(status=504, code="upstream_timeout", message=str(e))
        if isinstance(e, httpx.ConnectError):
            return CanonicalError(status=502, code="upstream_unreachable", message=str(e))
        return CanonicalError(status=502, code="upstream_error", message=str(e))
