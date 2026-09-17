from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
from typing import TYPE_CHECKING

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from airmux_runtime.observability import configure_logger, log_event
from data_plane.bundle import BundleHolder, build_bundle_source
from data_plane.config import Config, load_config
from data_plane.credentials import CredentialResolver
from data_plane.discovery import models
from data_plane.http import InferenceRoute, ResponseHeadersMiddleware
from data_plane.ingress import REGISTRY as INGRESS
from data_plane.metrics import DataPlaneMetrics, metrics_endpoint
from data_plane.outbox import build_outbox
from data_plane.proxy import complete
from data_plane.runtime import Runtime, runtime_of

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from starlette.requests import Request
    from starlette.types import ASGIApp

logger = logging.getLogger("data_plane")


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def readyz(request: Request) -> JSONResponse:
    runtime = runtime_of(request)
    holder = runtime.holder
    if not holder.current.snapshots:
        return JSONResponse({"status": "no bundle"}, status_code=503)
    if not runtime.outbox.accepting:
        return JSONResponse({"status": "metering unavailable"}, status_code=503)
    return JSONResponse({"status": "ready"})


def _build_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        http2=True,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        timeout=httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0),
    )


def _terminate_process() -> None:
    os.kill(os.getpid(), signal.SIGTERM)


def _terminate_process_on_failure(task: asyncio.Task[None], /) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is None:
        log_event(logger, logging.CRITICAL, "background_task_stopped", task=task.get_name(), outcome="failed")
    else:
        logger.critical(
            "background_task_failed",
            extra={"event": "background_task_failed", "fields": {"task": task.get_name(), "outcome": "failed"}},
            exc_info=error,
        )
    _terminate_process()


def create_app(config: Config) -> ASGIApp:
    metrics = DataPlaneMetrics()

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[dict[str, Runtime]]:
        configure_logger(logger, dev=config.dev)
        async with config.secrets.build() as secret_store, _build_http_client() as http_client:
            outbox = build_outbox(config.events, http_client, metrics)
            try:
                holder = BundleHolder(metrics)
                bundle_source = build_bundle_source(config.bundle, holder, http_client)
                runtime = Runtime(
                    holder=holder,
                    outbox=outbox,
                    credentials=CredentialResolver(secret_store, metrics),
                    http_client=http_client,
                    metrics=metrics,
                )
                async with asyncio.TaskGroup() as task_group:
                    tasks = (*bundle_source.start(task_group), *outbox.start(task_group))
                    for task in tasks:
                        task.add_done_callback(_terminate_process_on_failure)
                    try:
                        yield {"runtime": runtime}
                    finally:
                        for task in tasks:
                            task.cancel()
            finally:
                await outbox.close()

    app = Starlette(
        routes=[
            *(InferenceRoute(adapter.path, complete, ingress=adapter, methods=["POST"]) for adapter in INGRESS.values()),
            InferenceRoute("/inf/v1/models", models, ingress=INGRESS["openai_chat_completions"], methods=["GET"]),
            InferenceRoute("/inf/v1/models/{model_id:path}", models, ingress=INGRESS["openai_chat_completions"], methods=["GET"]),
            Route("/healthz", healthz),
            Route("/readyz", readyz),
            Route("/metrics", metrics_endpoint),
        ],
        lifespan=lifespan,
    )
    app.state.metrics = metrics
    return ResponseHeadersMiddleware(app, metrics)


def load_app() -> ASGIApp:
    return create_app(load_config())
