from __future__ import annotations

from typing import TYPE_CHECKING, cast

from model_audit.drivers.normalize import openai_responses, openai_responses_stream
from model_audit.drivers.wire import openai_responses_body
from model_audit.surfaces.base import SSEEvent, SurfaceCodec, payloads, stream_error

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic import JsonValue

    from model_audit.models import Case, Observation, Transport


class OpenAIResponsesCodec(SurfaceCodec):
    id = "oai_responses"
    endpoint = "responses"
    kind = "openai_responses"
    sdk_driver_id = "openai"
    priority = 0
    supports_continuation = True
    supported_fields = frozenset(
        {"messages", "max_tokens", "temperature", "top_p", "tools", "tool_choice", "parallel_tool_calls", "response_format", "reasoning"}
    )

    def encode(self, model: str, case: Case, transport: Transport) -> dict[str, JsonValue]:
        return openai_responses_body(model, case, transport)

    def decode_buffered(self, payload: Mapping[str, object], duration_ms: float) -> Observation:
        return openai_responses(payload, duration_ms, "HTTP JSON")

    def decode_stream(self, events: Sequence[SSEEvent], duration_ms: float) -> Observation:
        if error := stream_error(events, duration_ms):
            return error
        return openai_responses_stream(payloads(events), duration_ms, "HTTP SSE")

    def continuation(
        self,
        first: Mapping[str, object],
        response: Mapping[str, object],
        second: dict[str, object],
    ) -> dict[str, object]:
        second["input"] = [
            *cast("list[object]", first["input"]),
            *cast("list[object]", response.get("output") or []),
            *cast("list[object]", second["input"]),
        ]
        return second
