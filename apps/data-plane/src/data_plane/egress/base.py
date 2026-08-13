from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Literal
from uuid import UUID

import httpx
from pydantic import BaseModel

NIL_ORG = UUID(int=0)
NIL_WORKSPACE = UUID(int=0)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from contract import ModelEntry, ProviderEntry, Secret
    from data_plane.canonical import CanonicalChunk, CanonicalRequest, CanonicalResponse


class CanonicalError(BaseModel):
    status: int
    code: str
    message: str


def encode(body: BaseModel) -> bytes:
    """Wire bodies omit absent fields: a provider must never see a null it would reject."""
    return body.model_dump_json(exclude_none=True).encode()


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
    """Adapter-shaped accumulation across one stream; construct in new_stream_state, never in the transport."""

    buffer: bytes = b""


class UpstreamStreamError(Exception):
    """A provider error delivered as a stream event after a 200, outside the HTTP status path."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class Ctx:
    request_id: str
    model: ModelEntry
    provider: ProviderEntry
    stream: bool = False
    org_id: UUID = NIL_ORG
    workspace_id: UUID = NIL_WORKSPACE
    key_id: str = ""
    credential_id: UUID | None = None  # which provider key paid, stamped onto the usage event
    credential_scope: Literal["platform", "org", "workspace"] | None = None
    bundle_id: UUID | None = None
    started_at: float = field(default_factory=time.monotonic)


class EgressAdapter(ABC):
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
    def new_stream_state(self, ctx: Ctx) -> StreamState: ...

    @abstractmethod
    def frame(self, chunk: bytes, state: StreamState) -> Iterator[RawEvent]:
        """Bytes to wire events. Owns the framing and the partial-line buffer; the transport never parses SSE.

        Synchronous on purpose: the streaming path stays testable as a pure fold over a recorded byte log.
        """

    @abstractmethod
    def transform_stream_event(self, ev: RawEvent, state: StreamState) -> list[CanonicalChunk]:
        """One wire event into canonical chunks, folding what finalize needs into the state. Synchronous, like frame."""

    @abstractmethod
    def finalize(self, state: StreamState) -> CanonicalResponse:
        """Return a valid CanonicalResponse at ANY point in the stream.

        Called after the last event for a normal completion, and from the
        cancellation handler for partial accounting after a client disconnect.
        Usage lives on the response; cancel-and-still-meter depends on this
        being valid mid-stream.
        """

    def map_error(self, e: Exception) -> CanonicalError:
        """Transport failures mapped to a canonical error; override only for provider-specific codes."""
        if isinstance(e, UpstreamStreamError):
            return CanonicalError(status=502, code=e.code, message=e.message)
        if isinstance(e, httpx.TimeoutException):
            return CanonicalError(status=504, code="upstream_timeout", message=str(e))
        if isinstance(e, httpx.ConnectError):
            return CanonicalError(status=502, code="upstream_unreachable", message=str(e))
        return CanonicalError(status=502, code="upstream_error", message=str(e))
