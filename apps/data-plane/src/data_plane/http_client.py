from __future__ import annotations

import os
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from data_plane.config import HttpConfig


def build_http_client(config: HttpConfig) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(limit=config.max_connections),
        timeout=aiohttp.ClientTimeout(total=None, connect=5, sock_read=120),
        cookie_jar=aiohttp.DummyCookieJar(),
        trust_env=any(os.environ.get(name) for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy")),
    )
