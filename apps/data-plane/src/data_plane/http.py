from __future__ import annotations

import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from starlette.datastructures import MutableHeaders
from starlette.routing import Route

from contract import uuid7
from data_plane.auth import authenticate_request
from data_plane.egress.base import CanonicalError
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


@dataclass(frozen=True)
class InferenceContext:
    key: KeyEntry
    snapshot: BundleSnapshot
    start: RequestStart


type InferenceEndpoint = Callable[[Request, InferenceContext], Awaitable[Response]]


def render_rejection(ingress: IngressAdapter, error: RequestRejectedError) -> Response:
    return ingress.render_error(CanonicalError(status=error.status, code=error.code, message=error.message))


class InferenceRoute(Route):
    def __init__(self, path: str, endpoint: InferenceEndpoint, *, ingress: IngressAdapter, methods: list[str]) -> None:
        async def authenticated(request: Request) -> Response:
            try:
                key, snapshot = authenticate_request(request, runtime_of(request).holder)
                context = InferenceContext(key=key, snapshot=snapshot, start=cast("RequestStart", request.state.request_start))
                return await endpoint(request, context)
            except RequestRejectedError as error:
                return render_rejection(ingress, error)

        super().__init__(path, authenticated, methods=methods)


class ResponseHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = RequestStart(request_id=uuid7(), started_at=time.monotonic())
        scope["state"] = {**scope.get("state", {}), "request_start": start}

        async def send_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
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

        await self.app(scope, receive, send_headers)
