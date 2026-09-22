from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from data_plane.app import _build_http_client
from data_plane.config import HttpConfig


async def test_outbound_requests_reuse_connections_without_sharing_provider_cookies():
    async def respond(request: web.Request) -> web.Response:
        assert request.transport is not None
        response = web.json_response(
            {"peer": request.remote, "port": request.transport.get_extra_info("peername")[1], "cookie": request.headers.get("cookie")}
        )
        response.set_cookie("provider_session", "private")
        return response

    app = web.Application()
    app.router.add_get("/", respond)
    async with TestServer(app) as upstream, _build_http_client(HttpConfig()) as client:
        async with client.get(upstream.make_url("/")) as response:
            first = await response.json()
        async with client.get(upstream.make_url("/")) as response:
            second = await response.json()
    assert first["port"] == second["port"]
    assert first["cookie"] is None
    assert second["cookie"] is None


async def test_cancelling_a_stream_releases_the_connection_slot_before_upstream_finishes():
    release = asyncio.Event()

    async def streaming(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse()
        await response.prepare(request)
        await response.write(b"first")
        await release.wait()
        return response

    async def ready(_request: web.Request) -> web.Response:
        return web.Response(text="ready")

    app = web.Application()
    app.router.add_get("/stream", streaming)
    app.router.add_get("/ready", ready)
    async with TestServer(app) as upstream, _build_http_client(HttpConfig(max_connections=1)) as client:
        try:
            response = await client.get(upstream.make_url("/stream"))
            assert await response.content.readexactly(5) == b"first"

            async def next_request() -> str:
                async with client.get(upstream.make_url("/ready")) as next_response:
                    return await next_response.text()

            waiting = asyncio.create_task(next_request())
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(waiting), 0.05)
            response.close()
            assert await asyncio.wait_for(waiting, 1) == "ready"
            assert not release.is_set()
        finally:
            release.set()


async def test_outbound_read_timeout_does_not_exhaust_the_pool():
    release = asyncio.Event()

    async def streaming(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse()
        await response.prepare(request)
        await release.wait()
        return response

    app = web.Application()
    app.router.add_get("/", streaming)
    async with TestServer(app) as upstream, _build_http_client(HttpConfig(max_connections=1)) as client:
        try:
            with pytest.raises(TimeoutError):
                async with client.get(upstream.make_url("/"), timeout=aiohttp.ClientTimeout(sock_read=0.05)) as response:
                    await response.read()
            release.set()
            async with asyncio.timeout(1), client.get(upstream.make_url("/")) as response:
                assert await response.read() == b""
        finally:
            release.set()


async def test_data_plane_uses_the_environment_http_proxy(monkeypatch: pytest.MonkeyPatch):
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
    for variable in ("http_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{port}")
    async with server, _build_http_client(HttpConfig()) as client, client.get("http://provider.invalid/v1/models") as response:
        assert await response.text() == "ok"
    assert await request_lines.get() == "GET http://provider.invalid/v1/models HTTP/1.1"


async def test_paused_stream_applies_backpressure_to_the_provider():
    finished = asyncio.Event()
    body = b"x" * (16 * 1024 * 1024)

    async def streaming(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse()
        await response.prepare(request)
        await response.write(body)
        finished.set()
        return response

    app = web.Application()
    app.router.add_get("/", streaming)
    async with TestServer(app) as upstream, _build_http_client(HttpConfig()) as client, client.get(upstream.make_url("/")) as response:
        assert await response.content.readexactly(1) == b"x"
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(finished.wait(), 0.1)
        assert await asyncio.wait_for(response.read(), 2) == body[1:]
        assert finished.is_set()


async def test_provider_authentication_does_not_read_netrc_without_a_configured_proxy(tmp_path, monkeypatch):
    credentials = tmp_path / "netrc"
    credentials.write_text("machine 127.0.0.1 login unrelated password unrelated\n")
    monkeypatch.setenv("NETRC", str(credentials))
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)

    async def respond(request: web.Request) -> web.Response:
        return web.json_response({"authorization": request.headers.get("authorization")})

    app = web.Application()
    app.router.add_get("/", respond)
    async with TestServer(app) as upstream, _build_http_client(HttpConfig()) as client, client.get(upstream.make_url("/")) as response:
        assert await response.json() == {"authorization": None}
