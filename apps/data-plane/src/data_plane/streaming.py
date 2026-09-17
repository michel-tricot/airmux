from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio
import httpx
from starlette.responses import Response, StreamingResponse

from data_plane.egress.base import UpstreamProtocolError, UpstreamResponseError, UpstreamStreamError
from data_plane.metering import status_for_error, usage_event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.types import Receive, Scope, Send

    from contract import UsageEvent
    from data_plane.canonical import CanonicalAdjustment, CanonicalRequest
    from data_plane.egress.base import Ctx, EgressAdapter, StreamState, UpstreamRequest
    from data_plane.ingress import IngressAdapter
    from data_plane.outbox import OutboxReservation


@dataclass(frozen=True)
class StreamSession:
    adapter: EgressAdapter
    ingress: IngressAdapter
    ctx: Ctx
    request: CanonicalRequest
    adjustments: tuple[CanonicalAdjustment, ...]
    reservation: OutboxReservation
    http_client: httpx.AsyncClient

    async def open(self, upstream: UpstreamRequest) -> Response:
        async with contextlib.AsyncExitStack() as stack:
            response = await stack.enter_async_context(
                self.http_client.stream(upstream.method, upstream.url, headers=upstream.headers, content=upstream.body)
            )
            if response.is_error:
                body = await response.aread()
                raise UpstreamResponseError(response.status_code, body)
            stream_state = self.adapter.new_stream_state(self.ctx)
            handoff = stack.pop_all()

        return _StreamResponse(self, response, handoff, stream_state)


class _StreamResponse(StreamingResponse):
    def __init__(
        self,
        session: StreamSession,
        response: httpx.Response,
        handoff: contextlib.AsyncExitStack,
        stream_state: StreamState,
    ) -> None:
        self._session = session
        self._response = response
        self._handoff = handoff
        self._stream_state = stream_state
        self._renderer = session.ingress.new_stream()
        self._reservation = session.reservation.transfer()
        self._recorded = False
        super().__init__(self._events(), media_type="text/event-stream")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        with self._reservation:
            async with self._handoff:
                try:
                    await super().__call__(scope, receive, send)
                finally:
                    if not self._recorded:
                        self._record(self._cancelled_event())

    async def _events(self) -> AsyncIterator[bytes]:
        try:
            for frame in self._renderer.start(self._session.ctx):
                yield frame
            async for payload in self._response.aiter_bytes():
                for event in self._session.adapter.frame(payload, self._stream_state):
                    for canonical_chunk in self._session.adapter.transform_stream_event(event, self._stream_state):
                        for frame in self._renderer.chunk(canonical_chunk):
                            yield frame
            self._session.adapter.validate_stream(self._stream_state)
            final = self._session.adapter.finalize(self._stream_state)
            for frame in self._renderer.closing(final, list(self._session.adjustments)):
                yield frame
            self._record(usage_event(self._session.ctx, final, status="ok", request=self._session.request))
        except (UpstreamProtocolError, UpstreamStreamError, httpx.HTTPError) as error:
            for frame in self._renderer.error(self._session.adapter.map_error(error)):
                yield frame
            self._record(
                usage_event(
                    self._session.ctx,
                    self._session.adapter.finalize(self._stream_state),
                    status=status_for_error(error),
                    request=self._session.request,
                )
            )
        except (asyncio.CancelledError, anyio.get_cancelled_exc_class()):
            self._record(self._cancelled_event())
            raise

    def _cancelled_event(self) -> UsageEvent:
        return usage_event(
            self._session.ctx,
            self._session.adapter.finalize(self._stream_state),
            status="cancelled",
            request=self._session.request,
        )

    def _record(self, event: UsageEvent) -> None:
        self._reservation.record(event)
        self._recorded = True
