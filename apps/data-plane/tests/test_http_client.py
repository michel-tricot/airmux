from __future__ import annotations

import asyncio

import httpx2
import pytest

from data_plane.app import _build_http_client
from data_plane.config import HttpConfig


@pytest.mark.parametrize("config", [HttpConfig(), HttpConfig(max_connections=256, max_keepalive_connections=64)])
async def test_data_plane_uses_httpx2_for_outbound_requests(config):
    async with _build_http_client(config) as client:
        assert isinstance(client, httpx2.AsyncClient)
        assert client.timeout == httpx2.Timeout(connect=5, read=120, write=30, pool=5)
        transport = vars(client)["_transport"]
        pool = vars(transport)["_pool"]
        assert vars(pool)["_max_connections"] == config.max_connections
        assert vars(pool)["_max_keepalive_connections"] == config.max_keepalive_connections
        assert vars(pool)["_http2"] is True


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
    async with server, _build_http_client(HttpConfig()) as client:
        response = await client.get("http://provider.invalid/v1/models")
    assert response.text == "ok"
    assert await request_lines.get() == "GET http://provider.invalid/v1/models HTTP/1.1"
