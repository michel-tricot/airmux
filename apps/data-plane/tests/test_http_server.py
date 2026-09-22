from __future__ import annotations

import asyncio
import contextvars
import threading
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from starlette.requests import Request
from starlette.responses import Response
from uvicorn import Config
from uvicorn.server import ServerState

from data_plane.config import HttpConfig
from data_plane.http_client import build_http_client
from data_plane.http_server import RequestDispatchProtocol


@pytest.mark.parametrize("event_loop", ["asyncio", "uvloop"])
def test_received_request_reaches_provider_before_other_ready_tasks(event_loop):
    received = threading.Event()
    dispatched = []
    payload = b"provider request"

    class Provider(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            body = self.rfile.read(int(self.headers["content-length"]))
            received.set()
            self.send_response(200)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args, **kwargs):
            pass

    class PausingProtocol(RequestDispatchProtocol):
        def data_received(self, data):
            super().data_received(data)
            dispatched.append(received.wait(1))

    async def exchange(url):
        async with build_http_client(HttpConfig()) as client:
            async with client.post(url, data=b"warmup") as response:
                assert await response.read() == b"warmup"
            received.clear()

            async def forward(scope, receive, send):
                body = await Request(scope, receive).body()
                async with client.post(url, data=body) as response:
                    result = Response(await response.read())
                await result(scope, receive, send)

            config = Config(forward, lifespan="off", access_log=False)
            state = ServerState()
            server = await asyncio.get_running_loop().create_server(lambda: PausingProtocol(config, state, {}), "127.0.0.1", 0)
            async with server:
                port = server.sockets[0].getsockname()[1]
                async with client.post(f"http://127.0.0.1:{port}/", data=payload) as response:
                    assert await response.read() == payload
            await asyncio.gather(*state.tasks)

    factory = asyncio.new_event_loop if event_loop == "asyncio" else pytest.importorskip("uvloop").new_event_loop
    with ThreadingHTTPServer(("127.0.0.1", 0), Provider) as provider:
        server = threading.Thread(target=provider.serve_forever, daemon=True)
        server.start()
        try:
            with asyncio.Runner(loop_factory=factory) as runner:
                runner.run(exchange(f"http://127.0.0.1:{provider.server_port}/"))
        finally:
            provider.shutdown()
            server.join()
    assert dispatched == [True], "The provider request waited for another event-loop iteration"


@asynccontextmanager
async def connection(app, **options):
    config = Config(app, lifespan="off", access_log=False, **options)
    state = ServerState()
    server = await asyncio.get_running_loop().create_server(lambda: RequestDispatchProtocol(config, state, {}), "127.0.0.1", 0)
    async with server:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
        try:
            async with asyncio.timeout(5):
                yield reader, writer, state
        finally:
            writer.close()
            await writer.wait_closed()
            for task in tuple(state.tasks):
                task.cancel()
            await asyncio.gather(*state.tasks, return_exceptions=True)


async def read_response(reader):
    headers = await reader.readuntil(b"\r\n\r\n")
    content_length = next(int(header.split(b":", 1)[1]) for header in headers.split(b"\r\n") if header.lower().startswith(b"content-length:"))
    return headers.split(b"\r\n", 1)[0], await reader.readexactly(content_length)


@pytest.mark.parametrize("chunked", [False, True])
async def test_fragmented_upload_preserves_continue_and_request_body(chunked):
    payload = b"request body" * 65536

    async def echo(scope, receive, send):
        body = await Request(scope, receive).body()
        await Response(body)(scope, receive, send)

    async with connection(echo) as (reader, writer, state):
        encoding = b"Transfer-Encoding: chunked" if chunked else f"Content-Length: {len(payload)}".encode()
        writer.write(b"POST / HTTP/1.1\r\nHost: gateway\r\nExpect: 100-continue\r\n" + encoding + b"\r\n\r\n")
        assert await reader.readuntil(b"\r\n\r\n") == b"HTTP/1.1 100 Continue\r\n\r\n"
        for offset in range(0, len(payload), 32768):
            body = payload[offset : offset + 32768]
            writer.write(f"{len(body):x}\r\n".encode() + body + b"\r\n" if chunked else body)
            await writer.drain()
            await asyncio.sleep(0)
        if chunked:
            writer.write(b"0\r\n\r\n")
        assert await read_response(reader) == (b"HTTP/1.1 200 OK", payload)
        assert state.total_requests == 1


@pytest.mark.parametrize("suspend", [False, True])
async def test_pipeline_preserves_response_order_and_connection_reuse(suspend):
    async def echo(scope, receive, send):
        if suspend:
            await asyncio.sleep(0)
        await Response(scope["path"])(scope, receive, send)

    async with connection(echo) as (reader, writer, state):
        writer.write(b"".join(f"GET /{index} HTTP/1.1\r\nHost: gateway\r\n\r\n".encode() for index in range(20)))
        for index in range(20):
            assert await read_response(reader) == (b"HTTP/1.1 200 OK", f"/{index}".encode())
        writer.write(b"GET /reused HTTP/1.1\r\nHost: gateway\r\n\r\n")
        assert await read_response(reader) == (b"HTTP/1.1 200 OK", b"/reused")
        await asyncio.sleep(0)
        assert state.total_requests == 21
        assert not state.tasks


@pytest.mark.parametrize("reset_contextvars", [False, True])
@pytest.mark.parametrize("custom_factory", [False, True])
async def test_request_context_is_isolated_and_honors_task_factory(reset_contextvars, custom_factory):
    identity = contextvars.ContextVar("request_identity", default="empty")
    token = identity.set("parent")
    loop = asyncio.get_running_loop()
    original_factory = loop.get_task_factory()

    def instrumented_task(loop, coro, *, context=None, **kwargs):
        context = context if context is not None else contextvars.copy_context()
        context.run(identity.set, "instrumented")
        return asyncio.Task(coro, loop=loop, context=context, **kwargs)

    async def respond(scope, receive, send):
        inherited = identity.get()
        identity.set("request")
        await asyncio.sleep(0)
        await Response(f"{inherited}:{identity.get()}")(scope, receive, send)

    try:
        if custom_factory:
            loop.set_task_factory(instrumented_task)
        async with connection(respond, reset_contextvars=reset_contextvars) as (reader, writer, _):
            expected = "instrumented" if custom_factory else "empty" if reset_contextvars else "parent"
            for _ in range(2):
                writer.write(b"GET / HTTP/1.1\r\nHost: gateway\r\n\r\n")
                assert await read_response(reader) == (b"HTTP/1.1 200 OK", f"{expected}:request".encode())
            assert identity.get() == "parent"
    finally:
        loop.set_task_factory(original_factory)
        identity.reset(token)


async def test_request_timeout_keeps_connection_usable():
    async def respond(scope, receive, send):
        try:
            async with asyncio.timeout(0.01):
                if scope["path"] == "/timeout":
                    await asyncio.Event().wait()
            response = Response(b"ready")
        except TimeoutError:
            response = Response(b"deadline", status_code=504)
        await response(scope, receive, send)

    async with connection(respond) as (reader, writer, _):
        writer.write(b"GET /timeout HTTP/1.1\r\nHost: gateway\r\n\r\n")
        assert await read_response(reader) == (b"HTTP/1.1 504 Gateway Timeout", b"deadline")
        writer.write(b"GET / HTTP/1.1\r\nHost: gateway\r\n\r\n")
        assert await read_response(reader) == (b"HTTP/1.1 200 OK", b"ready")


async def test_configured_concurrency_limit_still_rejects_requests():
    async def respond(scope, receive, send):
        await Response(b"ready")(scope, receive, send)

    async with connection(respond, limit_concurrency=1) as (reader, writer, _):
        writer.write(b"GET / HTTP/1.1\r\nHost: gateway\r\n\r\n")
        assert await read_response(reader) == (b"HTTP/1.1 503 Service Unavailable", b"Service Unavailable")
        assert await reader.read() == b""
