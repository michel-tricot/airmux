"""The native dialect: the locked consumer surface from INTERFACE.md, translating nothing.

It exists on the ingress side because callers speak canonical; no provider does, which is why
the egress side has no counterpart module."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse

from data_plane.canonical import CanonicalChunk, CanonicalRequest, GatewayInfo
from data_plane.ingress.base import DONE, IngressAdapter, sse

if TYPE_CHECKING:
    from starlette.datastructures import Headers
    from starlette.responses import Response

    from data_plane.canonical import Adjustment, CanonicalResponse
    from data_plane.egress.base import CanonicalError, Ctx


class CanonicalResponseStream:
    """The native stream, exactly as INTERFACE.md locks it: delta frames, one closing chunk
    carrying finish_reason, usage and gateway with no delta, then [DONE]."""

    def start(self, ctx: Ctx) -> list[bytes]:  # noqa: ARG002 uniform ResponseStream signature
        return []

    def chunk(self, c: CanonicalChunk) -> list[bytes]:
        if c.delta is None:
            return []
        return [sse(c.model_dump_json(exclude_none=True).encode())]

    def closing(self, final: CanonicalResponse, adjustments: list[Adjustment]) -> list[bytes]:
        closing = CanonicalChunk(id=final.id, finish_reason=final.finish_reason, usage=final.usage, gateway=GatewayInfo(adjustments=adjustments))
        return [sse(closing.model_dump_json(exclude_none=True).encode()), DONE]

    def error(self, err: CanonicalError) -> list[bytes]:
        return [sse(json.dumps({"error": {"code": err.code, "message": err.message}}).encode()), DONE]


class CanonicalIngress(IngressAdapter):
    dialect = "canonical"

    def claims(self, headers: Headers, body: dict[str, Any]) -> bool:  # noqa: ARG002 uniform claims signature
        """Never claims: canonical is what resolve() falls back to when nobody else does."""
        return False

    def parse(self, body: dict[str, Any]) -> tuple[CanonicalRequest, list[Adjustment]]:
        return CanonicalRequest.model_validate(body), []

    def render_response(self, final: CanonicalResponse) -> Response:
        return JSONResponse(final.model_dump(mode="json", exclude_none=True))

    def render_error(self, err: CanonicalError) -> Response:
        return JSONResponse({"error": {"code": err.code, "message": err.message}}, status_code=err.status)

    def new_stream(self) -> CanonicalResponseStream:
        return CanonicalResponseStream()
