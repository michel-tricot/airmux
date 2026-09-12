from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

import httpx
from pydantic import BaseModel

from data_plane.canonical import CanonicalRequest

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from uuid import UUID

    from contract import CredentialScope, ModelEntry, ProviderEntry, Secret
    from data_plane.canonical import CanonicalChunk, CanonicalResponse


class CanonicalError(BaseModel):
    status: int
    code: str
    message: str


def encode(body: BaseModel | Mapping[str, Any], aliases: Mapping[str, str], extras: Mapping[str, Any]) -> bytes:
    """The wire body: typed fields spelled per the provider's aliases, then the forwardable
    extras merged after them, typed fields winning any collision. Absent fields are omitted:
    a provider must never see a null it would reject."""
    fields = body.model_dump(mode="json", exclude_none=True) if isinstance(body, BaseModel) else body
    token_parameters = CanonicalRequest.output_token_parameters
    token_spellings = token_parameters | {spelling for name, spelling in aliases.items() if name in token_parameters}
    if token_spellings.intersection(extras):
        message = "output token limits must use max_tokens"
        raise ValueError(message)
    if any(name not in token_parameters and aliases.get(name, name) in token_spellings for name in fields):
        message = "provider parameter aliases collide with output token limits"
        raise ValueError(message)
    rendered = {aliases.get(key, key): value for key, value in fields.items() if value is not None}
    return json.dumps({**dict(extras), **rendered}).encode()


@dataclass(frozen=True)
class UpstreamRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class RawEvent:
    data: bytes
    name: str | None = None


@dataclass
class StreamState:
    """Adapter-shaped accumulation across one stream; construct in new_stream_state, never in the transport.

    The base fields belong to frame_sse, the one SSE machine every adapter shares."""

    buffer: bytes = b""
    pending_name: str | None = None
    pending_data: list[bytes] = field(default_factory=list)


def frame_sse(chunk: bytes, state: StreamState) -> Iterator[RawEvent]:
    """The single source of truth for SSE framing: fix it here, every adapter is fixed.

    A synchronous fold, per the streaming rules. Spec-shaped where it matters: lines end with
    \\r\\n, \\n or \\r (a trailing \\r holds in the buffer until the next chunk says whether a
    \\n follows); an event dispatches on the blank line; multiple data lines concatenate with
    newlines; comment lines are ignored; the event name resets after dispatch. Adapters layer
    only their dialect on top, like OpenAI's [DONE] sentinel."""
    state.buffer += chunk
    working = state.buffer
    held = b""
    if working.endswith(b"\r"):
        working, held = working[:-1], b"\r"
    *lines, state.buffer = working.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
    state.buffer += held
    for line in lines:
        if not line:
            if state.pending_data:
                yield RawEvent(data=b"\n".join(state.pending_data), name=state.pending_name)
            state.pending_data = []
            state.pending_name = None
        elif line.startswith(b":"):
            continue
        elif line.startswith(b"event:"):
            state.pending_name = line[len(b"event:") :].strip().decode()
        elif line.startswith(b"data:"):
            state.pending_data.append(line[len(b"data:") :].strip())


class UpstreamStreamError(Exception):
    """A provider error delivered as a stream event after a 200, outside the HTTP status path."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class UpstreamResponseError(Exception):
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body
        super().__init__(f"upstream returned {status}")


class UpstreamProtocolError(ValueError):
    @classmethod
    def buffered_response(cls) -> UpstreamProtocolError:
        return cls("invalid upstream response")

    @classmethod
    def stream_event(cls) -> UpstreamProtocolError:
        return cls("invalid upstream stream event")

    @classmethod
    def incomplete_stream(cls) -> UpstreamProtocolError:
        return cls("upstream stream ended before its terminal event")


@dataclass(frozen=True)
class Ctx:
    request_id: UUID
    model: ModelEntry
    provider: ProviderEntry
    stream: bool
    org_id: UUID
    workspace_id: UUID
    key_id: str
    credential_id: UUID
    credential_scope: CredentialScope
    bundle_id: UUID
    started_at: float = field(default_factory=time.monotonic)


class EgressAdapter[StateT: StreamState](ABC):
    kind: ClassVar[str]

    def __init__(self, provider: ProviderEntry, credential: Secret) -> None:
        """The credential is injected because which key this request spends is decided per request:
        it depends on the caller's workspace and on which candidates are currently healthy, neither
        of which an adapter can see."""
        self.provider = provider
        self.credential = credential

    @abstractmethod
    def transform_request(self, req: CanonicalRequest, m: ModelEntry) -> UpstreamRequest: ...

    @abstractmethod
    def transform_response(self, raw: bytes, ctx: Ctx) -> CanonicalResponse: ...

    @abstractmethod
    def new_stream_state(self, ctx: Ctx) -> StateT: ...

    @abstractmethod
    def frame(self, chunk: bytes, state: StateT) -> Iterator[RawEvent]:
        """Bytes to wire events. Owns the framing and the partial-line buffer; the transport never parses SSE.

        Synchronous on purpose: the streaming path stays testable as a pure fold over a recorded byte log.
        """

    @abstractmethod
    def transform_stream_event(self, ev: RawEvent, state: StateT) -> list[CanonicalChunk]:
        """One wire event into canonical chunks, folding what finalize needs into the state. Synchronous, like frame."""

    @abstractmethod
    def validate_stream(self, state: StateT) -> None: ...

    @abstractmethod
    def finalize(self, state: StateT) -> CanonicalResponse:
        """Return a valid CanonicalResponse at ANY point in the stream.

        Called after the last event for a normal completion, and from the
        cancellation handler for partial accounting after a client disconnect.
        CanonicalUsage lives on the response; cancel-and-still-meter depends on this
        being valid mid-stream.
        """

    def map_error(self, error: Exception) -> CanonicalError:
        """Transport failures mapped to a canonical error; override only for provider-specific codes."""
        if isinstance(error, UpstreamResponseError):
            return CanonicalError(status=error.status, code="upstream_error", message="")
        if isinstance(error, UpstreamProtocolError):
            return CanonicalError(status=502, code="invalid_upstream_response", message=str(error))
        if isinstance(error, UpstreamStreamError):
            return CanonicalError(status=502, code=error.code, message=error.message)
        if isinstance(error, httpx.TimeoutException):
            return CanonicalError(status=504, code="upstream_timeout", message=str(error))
        if isinstance(error, httpx.ConnectError):
            return CanonicalError(status=502, code="upstream_unreachable", message=str(error))
        return CanonicalError(status=502, code="upstream_error", message=str(error))
