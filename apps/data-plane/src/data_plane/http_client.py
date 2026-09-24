from __future__ import annotations

import os
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from aiohttp.connector import Connection

    from data_plane.config import HttpConfig


class _ImmediateRequest(aiohttp.ClientRequest):
    async def send(self, conn: Connection) -> aiohttp.ClientResponse:
        if (transport := conn.transport) is not None:
            transport.set_write_buffer_limits(high=1)
        return await super().send(conn)


def build_http_client(config: HttpConfig) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=config.max_connections),
        timeout=aiohttp.ClientTimeout(total=None, connect=5, sock_read=120),
        cookie_jar=aiohttp.DummyCookieJar(),
        request_class=_ImmediateRequest,
        trust_env=any(os.environ.get(name) for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")),
    )
