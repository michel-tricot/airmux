from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Iterator

    from contract import ModelEntry, ProviderEntry
    from data_plane.canonical import (
        CanonicalChunk,
        CanonicalError,
        CanonicalRequest,
        CanonicalResponse,
        Ctx,
        RawEvent,
        StreamState,
        UpstreamRequest,
    )


class ProviderAdapter(ABC):
    kind: ClassVar[str]

    def __init__(self, provider: ProviderEntry) -> None:
        self.provider = provider

    @abstractmethod
    def validate_environment(self, p: ProviderEntry) -> None: ...

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

    @abstractmethod
    def map_error(self, e: Exception) -> CanonicalError: ...
