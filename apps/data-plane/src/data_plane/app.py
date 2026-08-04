from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from data_plane.holder import BundleHolder

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.requests import Request

holder = BundleHolder()


async def chat_completions(request: Request) -> JSONResponse:
    raise NotImplementedError


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def readyz(_request: Request) -> JSONResponse:
    if holder.current is None:
        return JSONResponse({"status": "no bundle"}, status_code=503)
    return JSONResponse({"status": "ready"})


@contextlib.asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    yield


app = Starlette(
    routes=[
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
        Route("/healthz", healthz),
        Route("/readyz", readyz),
    ],
    lifespan=lifespan,
)
