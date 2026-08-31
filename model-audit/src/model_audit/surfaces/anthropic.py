from __future__ import annotations

from typing import TYPE_CHECKING, cast

from model_audit.drivers.normalize import anthropic_message, anthropic_stream
from model_audit.drivers.wire import anthropic_body
from model_audit.surfaces.base import SSEEvent, SurfaceCodec, payloads, protocol_error, stream_error

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic import JsonValue

    from model_audit.models import Case, Observation, Transport


class AnthropicCodec(SurfaceCodec):
    id = "anthropic"
    endpoint = "messages"
    kind = "anthropic"
    sdk_driver_id = "anthropic"
    priority = 2
    supports_continuation = True
    supported_fields = frozenset(
        {"messages", "max_tokens", "temperature", "top_p", "stop", "tools", "tool_choice", "parallel_tool_calls", "response_format", "reasoning"}
    )

    def headers(self) -> dict[str, str]:
        return {"anthropic-version": "2023-06-01"}

    def encode(self, model: str, case: Case, transport: Transport) -> dict[str, JsonValue]:
        return anthropic_body(model, case, transport)

    def decode_buffered(self, payload: Mapping[str, object], duration_ms: float) -> Observation:
        return anthropic_message(payload, duration_ms, "HTTP JSON")

    def decode_stream(self, events: Sequence[SSEEvent], duration_ms: float) -> Observation:
        if error := stream_error(events, duration_ms):
            return error
        values = payloads(events)
        if not any(event.get("type") == "message_stop" for event in values):
            return protocol_error("provider stream ended before its terminal event", duration_ms)
        return anthropic_stream(values, duration_ms, "HTTP SSE")

    def continuation(
        self,
        first: Mapping[str, object],
        response: Mapping[str, object],
        second: dict[str, object],
    ) -> dict[str, object]:
        second["messages"] = [
            *cast("list[object]", first["messages"]),
            {"role": "assistant", "content": response.get("content") or []},
            *cast("list[object]", second["messages"]),
        ]
        return second
