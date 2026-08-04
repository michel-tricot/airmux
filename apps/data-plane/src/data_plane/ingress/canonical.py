from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.responses import JSONResponse, Response

from data_plane.canonical import CanonicalRequest
from data_plane.ingress.base import EgressStream, Ingress, sse

if TYPE_CHECKING:
    from data_plane.canonical import CanonicalChunk, CanonicalError, CanonicalResponse, Ctx


class CanonicalEgressStream(EgressStream):
    def start(self, ctx: Ctx) -> list[bytes]:  # noqa: ARG002 canonical egress has no preamble
        return []

    def chunk(self, c: CanonicalChunk) -> list[bytes]:
        return [b"data: " + c.model_dump_json().encode() + b"\n\n"]

    def finish(self, final: CanonicalResponse) -> list[bytes]:
        return [sse({"usage": final.usage.model_dump(), "finish_reason": final.finish_reason}), b"data: [DONE]\n\n"]

    def error(self, err: CanonicalError) -> list[bytes]:
        return [sse({"error": {"code": err.code, "message": err.message}})]


class CanonicalIngress(Ingress):
    """The gateway's own OpenAI-shaped surface at /v1/chat/completions."""

    def parse(self, body: bytes) -> CanonicalRequest:
        return CanonicalRequest.model_validate_json(body)

    def render_response(self, final: CanonicalResponse) -> Response:
        return Response(final.model_dump_json(), media_type="application/json")

    def render_error(self, err: CanonicalError) -> JSONResponse:
        return JSONResponse({"error": {"code": err.code, "message": err.message}}, status_code=err.status)

    def render_upstream_error(self, status_code: int, body: bytes) -> Response:
        return Response(body, status_code=status_code, media_type="application/json")

    def new_egress(self) -> EgressStream:
        return CanonicalEgressStream()
