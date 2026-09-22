from __future__ import annotations

from typing import TYPE_CHECKING

from robyn.testing import TestClient as RobynTestClient
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route

from data_plane.robyn_server import create_robyn_app

if TYPE_CHECKING:
    from starlette.requests import Request


async def response(_request: Request) -> Response:
    return Response(b"ok", headers={"x-request-id": "test"}, media_type="text/plain")


def test_robyn_adapter_preserves_response_body_and_headers() -> None:
    starlette_app = Starlette(routes=[Route("/response", response)])
    robyn_app = create_robyn_app(starlette_app, starlette_app.routes)

    result = RobynTestClient(robyn_app).get("/response")

    assert result.status_code == 200
    assert result.headers["content-type"] == "text/plain; charset=utf-8"
    assert result.headers["x-request-id"] == "test"
    assert result.text == "ok"
