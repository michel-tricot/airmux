from __future__ import annotations

from typing import Any, ClassVar, Self
from uuid import UUID

from sqlalchemy import text
from sqlmodel import Field, SQLModel

from contract import uuid7
from control_plane.db import current_session


def uuid7_pk() -> Any:  # noqa: ANN401 mirrors sqlmodel.Field, whose Any return lets the FieldInfo assign to a typed column
    """Server-minted time-ordered primary key: uuid7 client-side so the id exists before the first
    flush (audit self-attribution depends on that), native uuidv7() as the database backstop."""
    return Field(default_factory=uuid7, primary_key=True, sa_column_kwargs={"server_default": text("uuidv7()")})


class Identified(SQLModel):
    """Server-minted uuid7 primary key; models inherit the id and never declare it."""

    id: UUID = uuid7_pk()

    api_readonly: ClassVar[frozenset[str]] = frozenset({"id"})

    @classmethod
    async def find_by_id(cls, ident: UUID) -> Self | None:
        return await current_session().get(cls, ident)
