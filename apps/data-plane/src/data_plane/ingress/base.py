from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.responses import JSONResponse, Response

    from data_plane.canonical import CanonicalChunk, CanonicalError, CanonicalRequest, CanonicalResponse, Ctx


def sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode() + b"\n\n"


class EgressStream(ABC):
    """Renders the canonical stream into one client-facing wire format; stateful per request."""

    @abstractmethod
    def start(self, ctx: Ctx) -> list[bytes]: ...

    @abstractmethod
    def chunk(self, c: CanonicalChunk) -> list[bytes]: ...

    @abstractmethod
    def finish(self, final: CanonicalResponse) -> list[bytes]: ...

    @abstractmethod
    def error(self, err: CanonicalError) -> list[bytes]: ...


class Ingress(ABC):
    """A client-facing API surface: parse its request into canonical, render canonical back into its shape."""

    @abstractmethod
    def parse(self, body: bytes) -> CanonicalRequest: ...

    @abstractmethod
    def render_response(self, final: CanonicalResponse) -> Response: ...

    @abstractmethod
    def render_error(self, err: CanonicalError) -> JSONResponse:
        """A gateway-side failure (upstream unreachable, timeout) rendered in this surface's error shape."""

    @abstractmethod
    def render_upstream_error(self, status_code: int, body: bytes) -> Response:
        """An upstream 4xx/5xx passed back to the client in this surface's shape."""

    @abstractmethod
    def new_egress(self) -> EgressStream: ...
