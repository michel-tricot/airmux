from __future__ import annotations

import asyncio
import contextlib
import re
import time
from collections.abc import Awaitable, Callable, Generator, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, cast
from urllib.parse import urlencode

from robyn import Robyn, config
from robyn.responses import StreamingResponse as RobynStreamingResponse
from robyn.robyn import Headers
from robyn.robyn import Request as RobynRequest
from robyn.robyn import Response as RobynResponse
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from airmux_runtime.observability import request_context
from contract import uuid7
from data_plane.app import load_app
from data_plane.metering import RequestStart

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from starlette.applications import Starlette
    from starlette.types import Message, Receive, Scope

    from data_plane.http import ResponseHeadersMiddleware
    from data_plane.metrics import DataPlaneMetrics


type State = Mapping[str, object] | None
type Lifespan = Callable[[], AbstractAsyncContextManager[State]]
type Endpoint = Callable[[Request], Awaitable[Response]]
type StreamEvent = bytes | None


@dataclass
class RequestObservation:
    metrics: DataPlaneMetrics | None
    state: Mapping[str, object]
    route: str
    method: str
    started: float
    request_start: RequestStart
    finished: bool = False
    status: int = HTTPStatus.INTERNAL_SERVER_ERROR

    def finish(self, status: int) -> None:
        if self.metrics is not None and not self.finished:
            stream = bool(self.state["metrics_stream"])
            self.metrics.observe_inflight(self.route, stream, -1)
            self.metrics.observe_http((self.route, self.method, str(self.state["metrics_dialect"]), stream), status, time.monotonic() - self.started)
        self.finished = True


def create_robyn_app(starlette_app: Starlette, *, lifespan: Lifespan | None = None) -> Robyn:
    state: dict[str, object] = {}
    lifecycle: AbstractAsyncContextManager[State] | None = None
    robyn_app = Robyn(__file__, config=config)
    robyn_app.config.disable_openapi = True
    robyn_app.config.log_level = "WARNING"
    metrics = cast("DataPlaneMetrics | None", getattr(starlette_app.state, "metrics", None))

    @robyn_app.startup_handler
    async def startup() -> None:
        nonlocal lifecycle
        if lifespan is not None:
            lifecycle = lifespan()
            lifespan_state = await lifecycle.__aenter__()
            if lifespan_state is not None:
                state.update(lifespan_state)

    @robyn_app.shutdown_handler
    async def shutdown() -> None:
        if lifecycle is not None:
            await lifecycle.__aexit__(None, None, None)

    for route in starlette_app.routes:
        if isinstance(route, Route):
            for method in route.methods or ():
                endpoint = cast("Endpoint", route.endpoint)
                robyn_app.add_route(
                    method,
                    _robyn_path(route.path),
                    _handler(endpoint, route, starlette_app, state, metrics),
                    include_in_schema=False,
                )
    return robyn_app


def serve_robyn(*, host: str, port: int, workers: int) -> None:
    asgi_app = load_app()
    middleware = cast("ResponseHeadersMiddleware", asgi_app)
    starlette_app = cast("Starlette", middleware.app)
    config.processes = workers
    config.workers = 1
    create_robyn_app(
        starlette_app,
        lifespan=lambda: starlette_app.router.lifespan_context(starlette_app),
    ).start(host=host, port=port)


def _robyn_path(path: str) -> str:
    path = re.sub(r"\{([A-Za-z_]\w*):path\}", r"*\1", path)
    return re.sub(r"\{([A-Za-z_]\w*)\}", r":\1", path)


def _scope(request: RobynRequest, route: Route, app: Starlette, state: Mapping[str, object], start: RequestStart) -> Scope:
    url = request.url
    host = request.headers.get("host") or url.host
    raw_headers = [(name.encode("latin-1"), value.encode("latin-1")) for name, value in request.headers.multi_items()]
    raw_query = urlencode(request.query_params.to_dict(), doseq=True).encode("ascii")
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": request.method,
        "scheme": url.scheme,
        "path": url.path,
        "raw_path": url.path.encode("utf-8"),
        "query_string": raw_query,
        "root_path": "",
        "headers": raw_headers,
        "client": (request.ip_addr or "127.0.0.1", 0),
        "server": (host, 443 if url.scheme == "https" else 80),
        "state": {**state, "request_start": start, "metrics_route": route.path, "metrics_dialect": "none", "metrics_stream": False},
        "path_params": request.path_params,
        "app": app,
        "router": app.router,
        "extensions": {},
    }


def _receive(body: bytes) -> Receive:
    body_sent = False

    async def receive() -> Message:
        nonlocal body_sent
        if body_sent:
            return {"type": "http.disconnect"}
        body_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _handler(
    endpoint: Endpoint,
    route: Route,
    app: Starlette,
    state: Mapping[str, object],
    metrics: DataPlaneMetrics | None,
) -> Callable[[RobynRequest], object]:
    async def handle(request: RobynRequest) -> RobynResponse | RobynStreamingResponse:
        started = time.monotonic()
        request_start = RequestStart(request_id=uuid7(), started_at=started)
        scope = _scope(request, route, app, state, request_start)
        starlette_request = Request(scope, _receive(_request_body(request)))
        scope_state = cast("dict[str, object]", scope["state"])
        observation = RequestObservation(metrics, scope_state, route.path, request.method, started, request_start)
        if metrics is not None:
            metrics.observe_inflight(route.path, False, 1)
        try:
            with request_context(request_start.request_id):
                response = await endpoint(starlette_request)
            _response_headers(response, request_start.request_id)
            observation.status = response.status_code
            if isinstance(response, StreamingResponse):
                loop = asyncio.get_running_loop()
                events: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=1)
                producer = asyncio.create_task(_produce_stream(response, events, request_start))
                return RobynStreamingResponse(
                    _stream(events, loop, producer, observation),
                    status_code=response.status_code,
                    headers=_headers(response),
                    media_type=response.media_type or "application/octet-stream",
                )
            if request.method == "HEAD":
                response.body = b""
            result = RobynResponse(status_code=response.status_code, headers=_headers(response), body=bytes(response.body))
        except BaseException:
            observation.finish(HTTPStatus.INTERNAL_SERVER_ERROR)
            raise
        else:
            observation.finish(response.status_code)
            return result

    return handle


def _request_body(request: RobynRequest) -> bytes:
    return request.body.encode() if isinstance(request.body, str) else request.body


def _response_headers(response: Response, request_id: object) -> None:
    response.headers["x-request-id"] = str(request_id)
    response.headers["x-content-type-options"] = "nosniff"
    streaming = response.headers.get("content-type", "").partition(";")[0].strip().casefold() == "text/event-stream"
    response.headers["cache-control"] = "no-store, no-transform" if streaming else "no-store"
    if streaming:
        response.headers["x-accel-buffering"] = "no"
    if response.status_code == HTTPStatus.UNAUTHORIZED:
        response.headers.setdefault("www-authenticate", 'Bearer realm="airmux"')


def _headers(response: Response) -> Headers:
    headers = Headers({})
    for name, value in response.raw_headers:
        headers.append(name.decode("latin-1"), value.decode("latin-1"))
    return headers


async def _produce_stream(
    response: StreamingResponse,
    events: asyncio.Queue[StreamEvent],
    request_start: RequestStart,
) -> None:
    iterator = response.body_iterator.__aiter__()
    try:
        while True:
            with request_context(request_start.request_id):
                try:
                    chunk = await anext(iterator)
                except StopAsyncIteration:
                    await events.put(None)
                    return
            await events.put(chunk.encode() if isinstance(chunk, str) else bytes(chunk))
    finally:
        if close := getattr(iterator, "aclose", None):
            with contextlib.suppress(RuntimeError):
                await close()


def _stream(
    events: asyncio.Queue[StreamEvent],
    loop: asyncio.AbstractEventLoop,
    producer: asyncio.Task[None],
    observation: RequestObservation,
) -> Generator[bytes]:
    try:
        while (event := asyncio.run_coroutine_threadsafe(_next_stream_event(events, producer), loop).result()) is not None:
            yield event
    finally:
        try:
            asyncio.run_coroutine_threadsafe(_cancel(producer), loop).result()
        finally:
            observation.finish(observation.status)


async def _cancel(task: asyncio.Task[None]) -> None:
    if not task.done():
        task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _next_stream_event(events: asyncio.Queue[StreamEvent], producer: asyncio.Task[None]) -> bytes | None:
    if not events.empty():
        return events.get_nowait()
    if producer.done():
        producer.result()
        return None
    event = asyncio.create_task(events.get())
    done, _ = await asyncio.wait((event, producer), return_when=asyncio.FIRST_COMPLETED)
    if event in done:
        return event.result()
    event.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await event
    producer.result()
    return None
