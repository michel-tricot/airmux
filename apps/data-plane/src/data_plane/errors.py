from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data_plane.canonical import GatewayErrorCode


class RequestRejectedError(Exception):
    def __init__(self, status: int, code: GatewayErrorCode, message: str = "", *, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        self.status = status
        self.code = code
        self.message = message
        super().__init__(code)


class UnsupportedFeatureError(ValueError):
    pass
