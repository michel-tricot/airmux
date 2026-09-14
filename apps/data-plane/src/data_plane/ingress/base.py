from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from typing import Protocol

    from starlette.datastructures import Headers
    from starlette.responses import Response

    from data_plane.canonical import CanonicalAdjustment, CanonicalChunk, CanonicalRequest, CanonicalResponse
    from data_plane.egress.base import CanonicalError, Ctx

    class ResponseStream(Protocol):
        """How one dialect spells the canonical stream on the way out."""

        def start(self, ctx: Ctx, /) -> list[bytes]: ...

        def chunk(self, c: CanonicalChunk) -> list[bytes]: ...

        def closing(self, final: CanonicalResponse, adjustments: list[CanonicalAdjustment]) -> list[bytes]: ...

        def error(self, err: CanonicalError) -> list[bytes]: ...


DIALECT_HEADER = "x-tokkeeper-dialect"
DONE = b"data: [DONE]\n\n"


def sse(payload: bytes) -> bytes:
    return b"data: " + payload + b"\n\n"


class IngressAdapter(ABC):
    """One caller dialect: how requests in it become canonical, and how canonical answers speak it."""

    dialect: ClassVar[str]

    @abstractmethod
    def claims(self, headers: Headers, body: dict[str, Any], /) -> bool:
        """Is this request unmistakably mine? Answer only that; resolve() owns ordering and the default."""

    @abstractmethod
    def parse(self, body: dict[str, Any]) -> tuple[CanonicalRequest, list[CanonicalAdjustment]]:
        """The body into canonical, plus what this dialect could not carry across.

        Translation loss is an adjustment, never silence: a slot value the dialect cannot
        interpret is reported dropped, and the canonical field stays honestly unset."""

    @abstractmethod
    def render_response(self, final: CanonicalResponse) -> Response: ...

    @abstractmethod
    def render_error(self, err: CanonicalError) -> Response: ...

    @abstractmethod
    def new_stream(self) -> ResponseStream: ...
