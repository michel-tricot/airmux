from __future__ import annotations

from typing import TYPE_CHECKING

from model_audit.drivers.normalize import openai_chat, openai_chat_stream
from model_audit.drivers.wire import openai_chat_body
from model_audit.surfaces.base import SSEEvent, SurfaceCodec, payloads, protocol_error, stream_error

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic import JsonValue

    from model_audit.models import Case, Observation, Transport


class OpenAIChatCodec(SurfaceCodec):
    id = "oai"
    endpoint = "chat/completions"
    kind = "openai_compatible"
    sdk_driver_id = "openai"
    priority = 1
    supported_fields = frozenset(
        {
            "messages",
            "max_tokens",
            "temperature",
            "top_p",
            "stop",
            "seed",
            "logprobs",
            "top_logprobs",
            "tools",
            "tool_choice",
            "parallel_tool_calls",
            "response_format",
            "reasoning",
        }
    )

    def encode(self, model: str, case: Case, transport: Transport) -> dict[str, JsonValue]:
        return openai_chat_body(model, case, transport)

    def decode_buffered(self, payload: Mapping[str, object], duration_ms: float) -> Observation:
        return openai_chat(payload, duration_ms, "HTTP JSON")

    def decode_stream(self, events: Sequence[SSEEvent], duration_ms: float) -> Observation:
        if error := stream_error(events, duration_ms):
            return error
        if not any(event.data == "[DONE]" for event in events):
            return protocol_error("provider stream ended before its terminal event", duration_ms)
        return openai_chat_stream(payloads(events), duration_ms, "HTTP SSE")
