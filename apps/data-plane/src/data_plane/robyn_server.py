from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, cast
from urllib.parse import urlencode

from robyn import Robyn, config
from robyn.responses import StreamingResponse as RobynStreamingResponse
from robyn.robyn import Headers
from robyn.robyn import Request as RobynRequest
from robyn.robyn import Response as RobynResponse
from starlette.routing import BaseRoute, Route

from data_plane.app import load_app

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from starlette.applications import Starlette
    from starlette.types import ASGIApp, Message, Receive, Scope

    from data_plane.http import ResponseHeadersMiddleware


type State = Mapping[str, object] | None
type Lifespan = Callable[[], AbstractAsyncContextManager[State]]
type Event = Message | Exception


class ASGIProtocolError(RuntimeError):
    pass


def create_robyn_app(asgi_app: ASGIApp, routes: Sequence[BaseRoute], *, lifespan: Lifespan | None = None) -> Robyn:
    state: dict[str, object] = {}
    lifecycle: AbstractAsyncContextManager[State] | None = None
    robyn_app = Robyn(__file__, config=config)
    robyn_app.config.disable_openapi = True
    robyn_app.config.log_level = "WARNING"

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

    for route in routes:
        if isinstance(route, Route):
            for method in route.methods or ():
                robyn_app.add_route(method, _robyn_path(route.path), _handler(asgi_app, state), include_in_schema=False)
    return robyn_app


def serve_robyn(*, host: str, port: int, workers: int) -> None:
    asgi_app = load_app()
    middleware = cast("ResponseHeadersMiddleware", asgi_app)
    starlette_app = cast("Starlette", middleware.app)
    config.processes = workers
    config.workers = 1
    create_robyn_app(
        asgi_app,
        starlette_app.routes,
        lifespan=lambda: starlette_app.router.lifespan_context(starlette_app),
    ).start(host=host, port=port)


def _robyn_path(path: str) -> str:
    path = re.sub(r"\{([A-Za-z_]\w*):path\}", r"*\1", path)
    return re.sub(r"\{([A-Za-z_]\w*)\}", r":\1", path)


def _scope(request: RobynRequest, state: dict[str, object]) -> Scope:
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
        "state": state,
        "extensions": {},
    }


def _receiver(body: bytes, disconnected: asyncio.Event) -> Receive:
    body_sent = False

    async def receive() -> Message:
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    return receive


def _message(event: Event, expected: str) -> Message:
    if isinstance(event, Exception):
        raise event
    if event["type"] != expected:
        raise ASGIProtocolError
    return event


def _response_headers(message: Message) -> Headers:
    headers = Headers({})
    response_headers = cast("list[tuple[bytes, bytes]]", message["headers"])
    for name, value in response_headers:
        headers.append(name.decode("latin-1"), value.decode("latin-1"))
    return headers


def _handler(asgi_app: ASGIApp, state: dict[str, object]) -> Callable[[RobynRequest], object]:
    async def handle(request: RobynRequest) -> RobynResponse | RobynStreamingResponse:
        body = request.body.encode() if isinstance(request.body, str) else request.body
        disconnect = asyncio.Event()
        scope = _scope(request, state)
        events: asyncio.Queue[Event] = asyncio.Queue(maxsize=1)

        async def send(message: Message) -> None:
            await events.put(message)

        async def produce() -> None:
            try:
                await asgi_app(scope, _receiver(body, disconnect), send)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 ASGI exceptions must reach the response adapter
                await events.put(error)

        producer = asyncio.create_task(produce())
        try:
            response_start = _message(await events.get(), "http.response.start")
            first_body = _message(await events.get(), "http.response.body")
            status_code = cast("int", response_start["status"])
            headers = _response_headers(response_start)
            first_chunk = cast("bytes", first_body.get("body", b""))
            if not first_body.get("more_body", False):
                await producer
                return RobynResponse(status_code=status_code, headers=headers, body=first_chunk)
            return RobynStreamingResponse(
                _stream(events, producer, first_chunk, disconnect),
                status_code=status_code,
                headers=headers,
                media_type=headers.get("content-type") or "application/octet-stream",
            )
        except BaseException:
            if not producer.done():
                producer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await producer
            raise

    return handle


async def _stream(events: asyncio.Queue[Event], producer: asyncio.Task[None], first_chunk: bytes, disconnect: asyncio.Event) -> AsyncGenerator[bytes]:
    try:
        if first_chunk:
            yield first_chunk
        while True:
            event = _message(await events.get(), "http.response.body")
            chunk = cast("bytes", event.get("body", b""))
            if chunk:
                yield chunk
            if not event.get("more_body", False):
                await producer
                return
    finally:
        disconnect.set()
        if not producer.done():
            producer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer
