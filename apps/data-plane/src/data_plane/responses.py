from __future__ import annotations

from pydantic_core import to_json
from starlette.responses import Response


class JSONResponse(Response):
    media_type = "application/json"

    def __init__(self, content: object, status_code: int = 200, *, exclude_none: bool = False) -> None:
        super().__init__(to_json(content, by_alias=False, exclude_none=exclude_none), status_code=status_code)
