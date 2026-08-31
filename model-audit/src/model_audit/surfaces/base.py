from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from model_audit.models import EgressKind, Observation

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pydantic import JsonValue

    from model_audit.models import Case, Transport


@dataclass(frozen=True)
class SSEEvent:
    event: str | None
    data: str
    payload: Mapping[str, object] | None


def parse_sse(body: str) -> tuple[SSEEvent, ...]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        event = next((line.removeprefix("event:").strip() for line in block.splitlines() if line.startswith("event:")), None)
        data = "\n".join(line.removeprefix("data:").lstrip() for line in block.splitlines() if line.startswith("data:"))
        if not data:
            continue
        value = None if data == "[DONE]" else json.loads(data)
        payload = cast("Mapping[str, object]", value) if isinstance(value, dict) else None
        if payload is not None and event is not None and "type" not in payload:
            payload = {"type": event, **payload}
        events.append(SSEEvent(event=event, data=data, payload=payload))
    return tuple(events)


def payloads(events: Sequence[SSEEvent]) -> tuple[Mapping[str, object], ...]:
    return tuple(event.payload for event in events if event.payload is not None)


def stream_error(events: Sequence[SSEEvent], duration_ms: float) -> Observation | None:
    event = next(
        (
            item.payload
            for item in events
            if item.payload is not None and (item.payload.get("type") == "error" or isinstance(item.payload.get("error"), dict))
        ),
        None,
    )
    if event is None:
        return None
    detail = cast("Mapping[str, object]", event.get("error")) if isinstance(event.get("error"), dict) else event
    return Observation(
        outcome="error",
        error_code=str(detail.get("code") or detail.get("type") or "upstream_error"),
        error_message=str(detail.get("message") or ""),
        duration_ms=duration_ms,
        client_type="HTTP SSE",
    )


def protocol_error(message: str, duration_ms: float) -> Observation:
    return Observation(
        outcome="error",
        error_code="invalid_upstream_response",
        error_message=message,
        duration_ms=duration_ms,
        client_type="HTTP SSE",
    )


class SurfaceCodec(ABC):
    id: str
    endpoint: str
    kind: EgressKind
    sdk_driver_id: str
    priority: int
    supported_fields: frozenset[str]
    supports_continuation = False

    def headers(self) -> dict[str, str]:
        return {}

    @abstractmethod
    def encode(self, model: str, case: Case, transport: Transport) -> dict[str, JsonValue]: ...

    @abstractmethod
    def decode_buffered(self, payload: Mapping[str, object], duration_ms: float) -> Observation: ...

    @abstractmethod
    def decode_stream(self, events: Sequence[SSEEvent], duration_ms: float) -> Observation: ...

    def continuation(
        self,
        first: Mapping[str, object],
        response: Mapping[str, object],
        second: dict[str, object],
    ) -> dict[str, object]:
        _ = first, response, second
        message = f"{self.id} does not support provider-issued continuation state"
        raise ValueError(message)
