from __future__ import annotations

import time
from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi.routing import APIRoute
from starlette.datastructures import MutableHeaders
from starlette.routing import Route, compile_path

from airmux_runtime.observability import request_context
from contract import uuid7

if TYPE_CHECKING:
    from re import Pattern

    from fastapi import APIRouter
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from control_plane.metrics import ControlPlaneMetrics


def api_routes(routers: tuple[APIRouter, ...]) -> tuple[APIRoute, ...]:
    return tuple(route for router in routers for route in router.routes if isinstance(route, APIRoute))


def route_paths(routers: tuple[APIRouter, ...], *, prefix: str = "") -> tuple[str, ...]:
    return tuple(f"{prefix}{route.path}" for router in routers for route in router.routes if isinstance(route, Route))


class ObservabilityMiddleware:
    def __init__(self, app: ASGIApp, *, metrics: ControlPlaneMetrics, routes: tuple[str, ...]) -> None:
        self.app = app
        self.metrics = metrics
        self.routes: tuple[tuple[str, Pattern[str]], ...] = tuple((path, compile_path(path)[0]) for path in routes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid7()
        started_at = time.monotonic()
        route = self._route(scope)
        status = 500
        scope.setdefault("state", {})["request_id"] = request_id
        self.metrics.inflight.labels(route).inc()

        async def send_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {**message, "headers": list(message.get("headers", []))}
                MutableHeaders(scope=message)["x-request-id"] = str(request_id)
            await send(message)

        try:
            with request_context(request_id):
                await self.app(scope, receive, send_headers)
        finally:
            if route == "/api/v1/events":
                outcome = "success" if status < HTTPStatus.BAD_REQUEST else "rejected" if status < HTTPStatus.INTERNAL_SERVER_ERROR else "failed"
                self.metrics.event_ingest.labels(outcome).inc()
                self.metrics.event_ingest_duration.labels(outcome).observe(time.monotonic() - started_at)
            self.metrics.inflight.labels(route).dec()
            self.metrics.observe_http(route, scope["method"], status, time.monotonic() - started_at)

    def _route(self, scope: Scope) -> str:
        for path, pattern in self.routes:
            if pattern.match(scope["path"]):
                return path
        return "unmatched"
