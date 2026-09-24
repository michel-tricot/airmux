from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

import aiohttp
import anyio
from starlette.responses import Response, StreamingResponse

from data_plane.egress.base import UpstreamProtocolError, UpstreamResponseError, UpstreamStreamError
from data_plane.metering import status_for_error, usage_event
from data_plane.metrics import upstream_outcome

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Iterator

    from starlette.types import Receive, Scope, Send

    from contract import UsageEvent
    from data_plane.canonical import CanonicalAdjustment, CanonicalRequest
    from data_plane.egress.base import Ctx, EgressAdapter, StreamState, UpstreamRequest
    from data_plane.ingress import IngressAdapter
    from data_plane.metrics import DataPlaneMetrics, UpstreamOutcome
    from data_plane.outbox import OutboxReservation

_MAX_STREAM_BATCH_BYTES = 65_536


@dataclass(frozen=True)
class StreamSession:
    adapter: EgressAdapter
    ingress: IngressAdapter
    ctx: Ctx
    request: CanonicalRequest
    adjustments: tuple[CanonicalAdjustment, ...]
    reservation: OutboxReservation
    http_client: aiohttp.ClientSession
    metrics: DataPlaneMetrics
    egress_kind: str
    attempt_started_at: float

    async def open(self, upstream: UpstreamRequest) -> Response:
        async with contextlib.AsyncExitStack() as stack:
            response = await stack.enter_async_context(
                self.http_client.request(upstream.method, upstream.url, headers=upstream.headers, data=upstream.body, allow_redirects=False)
            )
            if response.status >= HTTPStatus.BAD_REQUEST:
                body = await response.read()
                raise UpstreamResponseError(response.status, body)
            stream_state = self.adapter.new_stream_state(self.ctx)
            handoff = stack.pop_all()

        return _StreamResponse(self, response, handoff, stream_state)


class _StreamResponse(StreamingResponse):
    def __init__(
        self,
        session: StreamSession,
        response: aiohttp.ClientResponse,
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
        self._event_stream = self._events()
        super().__init__(self._event_stream, media_type="text/event-stream")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        with self._reservation:
            async with self._handoff, contextlib.aclosing(self._event_stream):
                try:
                    await super().__call__(scope, receive, send)
                finally:
                    if not self._recorded:
                        self._record(self._cancelled_event(), "cancelled")

    async def _events(self) -> AsyncGenerator[bytes]:
        try:
            for frame in self._renderer.start(self._session.ctx):
                yield frame
            async for payload in self._response.content.iter_any():
                for batch in self._render_payload(payload):
                    yield batch
            self._session.adapter.validate_stream(self._stream_state)
            final = self._session.adapter.finalize(self._stream_state)
            for frame in self._renderer.closing(final, list(self._session.adjustments)):
                yield frame
            self._record(usage_event(self._session.ctx, final, status="ok", request=self._session.request), "success")
        except (UpstreamProtocolError, UpstreamStreamError, aiohttp.ClientError, TimeoutError) as error:
            for frame in self._renderer.error(self._session.adapter.map_error(error)):
                yield frame
            self._record(
                usage_event(
                    self._session.ctx,
                    self._session.adapter.finalize(self._stream_state),
                    status=status_for_error(error),
                    request=self._session.request,
                ),
                upstream_outcome(error),
            )
        except (asyncio.CancelledError, anyio.get_cancelled_exc_class()):
            self._record(self._cancelled_event(), "cancelled")
            raise

    def _render_payload(self, payload: bytes) -> Iterator[bytes]:
        batch = bytearray()
        try:
            for event in self._session.adapter.frame(payload, self._stream_state):
                for canonical_chunk in self._session.adapter.transform_stream_event(event, self._stream_state):
                    for frame in self._renderer.chunk(canonical_chunk):
                        batch.extend(frame)
                        if len(batch) >= _MAX_STREAM_BATCH_BYTES:
                            yield bytes(batch)
                            batch.clear()
        except Exception:
            if batch:
                yield bytes(batch)
            raise
        if batch:
            yield bytes(batch)

    def _cancelled_event(self) -> UsageEvent:
        return usage_event(
            self._session.ctx,
            self._session.adapter.finalize(self._stream_state),
            status="cancelled",
            request=self._session.request,
        )

    def _record(self, event: UsageEvent, outcome: UpstreamOutcome) -> None:
        self._reservation.record(event)
        self._session.metrics.observe_upstream(self._session.egress_kind, outcome, self._session.attempt_started_at)
        self._recorded = True
