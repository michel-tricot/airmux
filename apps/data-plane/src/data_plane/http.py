from __future__ import annotations

import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from starlette.datastructures import MutableHeaders
from starlette.routing import Match, Route

from airmux_runtime.observability import request_context
from contract import uuid7
from data_plane.auth import authenticate_request
from data_plane.canonical import CanonicalError
from data_plane.errors import RequestRejectedError
from data_plane.metering import RequestStart
from data_plane.runtime import runtime_of

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from contract import KeyEntry
    from data_plane.bundle.holder import BundleSnapshot
    from data_plane.ingress import IngressAdapter
    from data_plane.metrics import DataPlaneMetrics


@dataclass(frozen=True)
class InferenceContext:
    key: KeyEntry
    snapshot: BundleSnapshot
    start: RequestStart


type InferenceEndpoint = Callable[[Request, InferenceContext, IngressAdapter], Awaitable[Response]]


def render_rejection(ingress: IngressAdapter, error: RequestRejectedError) -> Response:
    return ingress.render_error(CanonicalError(status=error.status, code=error.code, message=error.message))


class InferenceRoute(Route):
    def __init__(self, path: str, endpoint: InferenceEndpoint, *, ingress: IngressAdapter, methods: list[str]) -> None:
        async def authenticated(request: Request) -> Response:
            request.scope["state"]["metrics_dialect"] = ingress.dialect
            try:
                key, snapshot = authenticate_request(request, runtime_of(request).holder)
                context = InferenceContext(key=key, snapshot=snapshot, start=cast("RequestStart", request.state.request_start))
                return await endpoint(request, context, ingress)
            except RequestRejectedError as error:
                return render_rejection(ingress, error)

        super().__init__(path, authenticated, methods=methods)


class ResponseHeadersMiddleware:
    def __init__(self, app: ASGIApp, metrics: DataPlaneMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = RequestStart(request_id=uuid7(), started_at=time.monotonic())
        route = self._route(scope)
        stream = False
        scope["state"] = {
            **scope.get("state", {}),
            "request_start": start,
            "metrics_route": route,
            "metrics_dialect": "none",
            "metrics_stream": stream,
        }
        self.metrics.observe_inflight(route, stream, 1)
        status = 500

        async def send_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {**message, "headers": list(message.get("headers", []))}
                headers = MutableHeaders(scope=message)
                headers["x-request-id"] = str(start.request_id)
                headers["x-content-type-options"] = "nosniff"
                streaming = headers.get("content-type", "").partition(";")[0].strip().casefold() == "text/event-stream"
                headers["cache-control"] = "no-store, no-transform" if streaming else "no-store"
                if streaming:
                    headers["x-accel-buffering"] = "no"
                if message["status"] == HTTPStatus.UNAUTHORIZED:
                    headers.setdefault("www-authenticate", 'Bearer realm="airmux"')
            await send(message)

        try:
            with request_context(start.request_id):
                await self.app(scope, receive, send_headers)
        finally:
            state = scope["state"]
            actual_stream = bool(state["metrics_stream"])
            self.metrics.observe_inflight(route, actual_stream, -1)
            self.metrics.observe_http(
                (route, scope["method"], str(state["metrics_dialect"]), actual_stream),
                status,
                time.monotonic() - start.started_at,
            )

    def _route(self, scope: Scope) -> str:
        for route in getattr(self.app, "routes", ()):
            match, _ = route.matches(scope)
            if match is Match.FULL:
                return cast("Route", route).path
        return "unmatched"
