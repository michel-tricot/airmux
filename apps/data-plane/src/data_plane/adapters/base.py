from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

import httpx

from data_plane.canonical import CanonicalError, UpstreamStreamError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from contract import ModelEntry, ProviderEntry, Secret
    from data_plane.canonical import (
        CanonicalChunk,
        CanonicalRequest,
        CanonicalResponse,
        Ctx,
        RawEvent,
        StreamState,
        UpstreamRequest,
    )


class ProviderAdapter(ABC):
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
    def frame(self, chunk: bytes, state: StreamState) -> Iterator[RawEvent]: ...

    @abstractmethod
    def transform_stream_event(self, ev: RawEvent, state: StreamState) -> list[CanonicalChunk]: ...

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
