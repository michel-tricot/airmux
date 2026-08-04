from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.adapters.base import ProviderAdapter

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


class AnthropicAdapter(ProviderAdapter):
    kind = "anthropic"

    def validate_environment(self, p: ProviderEntry) -> None:
        raise NotImplementedError

    def transform_request(self, req: CanonicalRequest, m: ModelEntry) -> UpstreamRequest:
        raise NotImplementedError

    def transform_response(self, raw: bytes, ctx: Ctx) -> CanonicalResponse:
        raise NotImplementedError

    def new_stream_state(self, ctx: Ctx) -> StreamState:
        raise NotImplementedError

    def frame(self, chunk: bytes, state: StreamState) -> Iterator[RawEvent]:
        raise NotImplementedError

    def transform_stream_event(self, ev: RawEvent, state: StreamState) -> list[CanonicalChunk]:
        raise NotImplementedError

    def finalize(self, state: StreamState) -> CanonicalResponse:
        raise NotImplementedError

    def map_error(self, e: Exception) -> CanonicalError:
        raise NotImplementedError
