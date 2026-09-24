from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from pyreqwest.client import ClientBuilder

from data_plane.config import HttpConfig
from data_plane.metering import status_for_error
from data_plane.provider_http_client import ProviderHttpClient, build_provider_http_client


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
            async with client.request("POST", str(upstream.make_url("/")), headers={}, data=b"payload") as response:
                assert await response.read() == b"payload"
    assert len(set(ports)) == 1


async def test_provider_read_timeout_is_classified_as_timeout():
    release = asyncio.Event()

    async def stalled(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse()
        await response.prepare(request)
        await release.wait()
        return response

    app = web.Application()
    app.router.add_get("/", stalled)
    client = ProviderHttpClient(ClientBuilder().read_timeout(timedelta(milliseconds=50)).no_proxy().build())
    async with TestServer(app) as upstream, client:
        try:
            with pytest.raises(TimeoutError) as error:
                async with client.request("GET", str(upstream.make_url("/")), headers={}) as response:
                    await response.read()
            assert status_for_error(error.value) == "timeout"
        finally:
            release.set()


async def test_cancelled_provider_stream_releases_connection_before_upstream_finishes():
    release = asyncio.Event()

    async def streaming(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse()
        await response.prepare(request)
        await response.write(b"first")
        await release.wait()
        await response.write_eof()
        return response

    async def ready(_request: web.Request) -> web.Response:
        return web.Response(text="ready")

    app = web.Application()
    app.router.add_get("/stream", streaming)
    app.router.add_get("/ready", ready)
    async with TestServer(app) as upstream, build_provider_http_client(HttpConfig(max_connections=1)) as client:
        async with client.request("GET", str(upstream.make_url("/stream")), headers={}, stream=True) as response:
            assert not release.is_set()
            first_chunk = await asyncio.wait_for(anext(response.iter_any()), 0.2)
            assert not release.is_set()
            assert first_chunk == b"first"
            waiting = asyncio.create_task(_get_provider_body(client, str(upstream.make_url("/ready"))))
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(waiting), 0.05)
        assert not release.is_set()
        assert await asyncio.wait_for(waiting, 1) == b"ready"
        assert not release.is_set()


async def _get_provider_body(client: ProviderHttpClient, url: str) -> bytes:
    async with client.request("GET", url, headers={}) as response:
        return await response.read()


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
