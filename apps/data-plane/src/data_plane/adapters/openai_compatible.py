from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from data_plane.adapters.base import ProviderAdapter
from data_plane.canonical import CanonicalChunk, CanonicalError, CanonicalResponse, RawEvent, StreamState, UpstreamRequest, UpstreamStreamError, Usage
from data_plane.secrets import resolve

if TYPE_CHECKING:
    from collections.abc import Iterator

    from contract import ModelEntry, ProviderEntry
    from data_plane.canonical import CanonicalRequest, Ctx


@dataclass
class OpenAIStreamState(StreamState):
    ctx: Ctx | None = None
    response_id: str | None = None
    text: list[str] = field(default_factory=list)
    tool_calls: dict[int, dict[str, Any]] = field(default_factory=dict)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


class OpenAICompatibleAdapter(ProviderAdapter):
    kind = "openai_compatible"

    def validate_environment(self, p: ProviderEntry) -> None:
        resolve(p.credential_ref)

    def transform_request(self, req: CanonicalRequest, m: ModelEntry) -> UpstreamRequest:
        optional = {"max_tokens": req.max_tokens, "temperature": req.temperature, "tools": req.tools}
        stream_fields: dict[str, Any] = {"stream": True, "stream_options": {"include_usage": True}} if req.stream else {}
        body = {
            "model": m.upstream_model,
            "messages": req.messages,
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
        text_content = [{"type": "text", "text": message["content"]}] if message.get("content") is not None else []
        tool_content = [{"type": "tool_call", "id": tc.get("id"), "function": tc.get("function") or {}} for tc in message.get("tool_calls") or []]
        usage = data.get("usage") or {}
        return CanonicalResponse(
            id=data.get("id", ctx.request_id),
            model=ctx.model.model_id,
            content=[*text_content, *tool_content],
            finish_reason=choice.get("finish_reason"),
            usage=Usage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                estimated=not usage,
            ),
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
        chunk_id = state.response_id or (state.ctx.request_id if state.ctx else "")
        chunks: list[CanonicalChunk] = []
        for choice in data.get("choices") or []:
            delta = choice.get("delta") or {}
            finish = choice.get("finish_reason")
            if finish:
                state.finish_reason = finish
            content = delta.get("content")
            if content:
                state.text.append(content)
                chunks.append(CanonicalChunk(id=chunk_id, delta={"type": "text", "text": content}, finish_reason=finish))
            for tc in delta.get("tool_calls") or []:
                index = tc.get("index", 0)
                slot = state.tool_calls.setdefault(index, {"id": None, "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
                chunks.append(
                    CanonicalChunk(id=chunk_id, delta={"type": "tool_call", "index": index, "id": tc.get("id"), "function": fn}, finish_reason=finish)
                )
            if finish and not content and not delta.get("tool_calls"):
                chunks.append(CanonicalChunk(id=chunk_id, delta={}, finish_reason=finish))
        return chunks

    def finalize(self, state: StreamState) -> CanonicalResponse:
        """Return a valid CanonicalResponse at ANY point in the stream.

        Called after the last event for a normal completion, and from the
        cancellation handler for partial accounting after a client disconnect.
        """
        assert isinstance(state, OpenAIStreamState)  # noqa: S101 state comes from new_stream_state
        text = "".join(state.text)
        text_content = [{"type": "text", "text": text}] if text else []
        tool_content = [{"type": "tool_call", **state.tool_calls[index]} for index in sorted(state.tool_calls)]
        usage = state.usage or {}
        return CanonicalResponse(
            id=state.response_id or (state.ctx.request_id if state.ctx else ""),
            model=state.ctx.model.model_id if state.ctx else "",
            content=[*text_content, *tool_content],
            finish_reason=state.finish_reason,
            usage=Usage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                estimated=not usage,
            ),
        )

    def map_error(self, e: Exception) -> CanonicalError:
        if isinstance(e, UpstreamStreamError):
            return CanonicalError(status=502, code=e.code, message=e.message)
        if isinstance(e, httpx.TimeoutException):
            return CanonicalError(status=504, code="upstream_timeout", message=str(e))
        if isinstance(e, httpx.ConnectError):
            return CanonicalError(status=502, code="upstream_unreachable", message=str(e))
        return CanonicalError(status=502, code="upstream_error", message=str(e))
