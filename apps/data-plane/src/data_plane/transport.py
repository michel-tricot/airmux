from __future__ import annotations

import httpx

client = httpx.AsyncClient(
    http2=True,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    timeout=httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0),
)
