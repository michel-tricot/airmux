from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

import pytest
from robyn.testing import TestClient as RobynTestClient
from starlette.applications import Starlette
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from contract import uuid7
from data_plane.metering import RequestStart
from data_plane.robyn_server import _produce_stream, create_robyn_app

if TYPE_CHECKING:
    from starlette.requests import Request


async def response(_request: Request) -> Response:
    return Response(b"ok", headers={"x-request-id": "test"}, media_type="text/plain")


async def query(request: Request) -> Response:
    return Response(json.dumps({"path": request.url.path, "query": request.query_params.get("q")}))


def test_robyn_native_route_preserves_response_body_and_headers() -> None:
    starlette_app = Starlette(routes=[Route("/response", response)])
    robyn_app = create_robyn_app(starlette_app)

    result = RobynTestClient(robyn_app).get("/response")

    assert result.status_code == 200
    assert result.headers["content-type"] == "text/plain; charset=utf-8"
    assert result.headers["x-request-id"]
    assert result.text == "ok"


def test_robyn_native_route_preserves_query_parameters() -> None:
    starlette_app = Starlette(routes=[Route("/query", query)])
    robyn_app = create_robyn_app(starlette_app)

    result = RobynTestClient(robyn_app).get("/query", query_params={"q": "hello world"})

    assert result.status_code == 200
    assert result.json() == {"path": "/query", "query": "hello world"}


@pytest.mark.asyncio
async def test_robyn_native_stream_cancellation_closes_source() -> None:
    stream_closed = asyncio.Event()

    async def chunks():
        try:
            yield b"first"
            await asyncio.Event().wait()
        finally:
            stream_closed.set()

    response = StreamingResponse(chunks())
    events: asyncio.Queue[bytes | Exception | None] = asyncio.Queue(maxsize=1)
    request_start = RequestStart(request_id=uuid7(), started_at=time.monotonic())
    producer = asyncio.create_task(_produce_stream(response, events, request_start))

    assert await events.get() == b"first"
    producer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await producer

    assert stream_closed.is_set()
