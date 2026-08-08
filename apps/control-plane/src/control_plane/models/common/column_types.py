from __future__ import annotations

from sqlalchemy import DateTime


class UTCDateTime(DateTime):
    """timestamptz for every datetime column: asyncpg rejects aware datetimes on naive columns, and this codebase is aware-only."""

    def __init__(self) -> None:
        super().__init__(timezone=True)
