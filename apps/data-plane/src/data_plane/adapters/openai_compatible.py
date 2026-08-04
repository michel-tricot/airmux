from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from data_plane.adapters.base import ProviderAdapter
from data_plane.canonical import CanonicalError, CanonicalResponse, UpstreamRequest, Usage
from data_plane.secrets import resolve

if TYPE_CHECKING:
    from collections.abc import Iterator

    from contract import ModelEntry, ProviderEntry
    from data_plane.canonical import CanonicalChunk, CanonicalRequest, Ctx, RawEvent, StreamState


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
        tool_content = [{"type": "tool_call", **tc} for tc in message.get("tool_calls") or []]
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

    def new_stream_state(self, ctx: Ctx) -> StreamState:
        raise NotImplementedError

    def frame(self, chunk: bytes, state: StreamState) -> Iterator[RawEvent]:
        raise NotImplementedError

    def transform_stream_event(self, ev: RawEvent, state: StreamState) -> list[CanonicalChunk]:
        raise NotImplementedError

    def finalize(self, state: StreamState) -> CanonicalResponse:
        raise NotImplementedError

    def map_error(self, e: Exception) -> CanonicalError:
        if isinstance(e, httpx.TimeoutException):
            return CanonicalError(status=504, code="upstream_timeout", message=str(e))
        if isinstance(e, httpx.ConnectError):
            return CanonicalError(status=502, code="upstream_unreachable", message=str(e))
        return CanonicalError(status=502, code="upstream_error", message=str(e))
