from __future__ import annotations

from pydantic import BaseModel


class Envelope[T](BaseModel):
    """Every admin API response is {"data": <payload>}; the /v1 plane-sync contract is exempt."""

    data: T
