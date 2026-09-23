from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiohttp import web
from aiohttp.test_utils import TestServer

from data_plane.config import HttpConfig
from data_plane.provider_http_client import build_provider_http_client

if TYPE_CHECKING:
    import pytest


async def test_buffered_provider_response_is_fully_read_and_connection_reused():
    ports: list[int] = []

    async def respond(request: web.Request) -> web.Response:
        assert request.transport is not None
        ports.append(request.transport.get_extra_info("peername")[1])
        return web.Response(body=await request.read())

    app = web.Application()
    app.router.add_post("/", respond)
    async with TestServer(app) as upstream, build_provider_http_client(HttpConfig()) as client:
        for _ in range(2):
            async with client.request("POST", upstream.make_url("/"), headers={}, data=b"payload") as response:
                assert await response.read() == b"payload"
    assert len(set(ports)) == 1


async def test_provider_requests_use_the_configured_http_proxy(monkeypatch: pytest.MonkeyPatch):
    request_lines: asyncio.Queue[str] = asyncio.Queue()

    async def proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request_lines.put_nowait((await reader.readline()).decode().rstrip())
        while await reader.readline() not in (b"\r\n", b""):
            pass
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(proxy, "127.0.0.1", 0)
    assert server.sockets
    port = server.sockets[0].getsockname()[1]
    for variable in ("http_proxy", "https_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{port}")
    async with (
        server,
        build_provider_http_client(HttpConfig()) as client,
        client.request("GET", "http://provider.invalid/v1/models", headers={}) as response,
    ):
        assert await response.read() == b"ok"
    assert await request_lines.get() == "GET http://provider.invalid/v1/models HTTP/1.1"
