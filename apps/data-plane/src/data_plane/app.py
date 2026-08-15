from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from data_plane.bundle import BundleHolder, build_bundle_source
from data_plane.config import Config, load_config
from data_plane.credentials import CredentialResolver
from data_plane.outbox import build_outbox
from data_plane.proxy import complete, messages
from data_plane.runtime import Runtime, runtime_of

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.requests import Request

logger = logging.getLogger("data_plane")


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def readyz(request: Request) -> JSONResponse:
    if runtime_of(request).holder.snapshot is None:
        return JSONResponse({"status": "no bundle"}, status_code=503)
    return JSONResponse({"status": "ready"})


def _configure_dev_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def create_app(config: Config) -> Starlette:
    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[dict[str, Runtime]]:
        if config.dev:
            _configure_dev_logging()
        async with httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            timeout=httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0),
        ) as http_client:
            outbox = build_outbox(config.events, config.control_plane, http_client)
            try:
                holder = BundleHolder()
                bundle_source = build_bundle_source(config.bundle, config.control_plane, holder, http_client)
                runtime = Runtime(
                    holder=holder,
                    outbox=outbox,
                    credentials=CredentialResolver(config.secrets.build()),
                    http_client=http_client,
                )
                tasks = (*bundle_source.start(), *outbox.start())
                try:
                    yield {"runtime": runtime}
                finally:
                    for task in tasks:
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
            finally:
                outbox.close()

    return Starlette(
        routes=[
            Route("/v1/chat/completions", complete, methods=["POST"]),
            Route("/v1/messages", messages, methods=["POST"]),
            Route("/healthz", healthz),
            Route("/readyz", readyz),
        ],
        lifespan=lifespan,
    )


def load_app() -> Starlette:
    return create_app(load_config())
