from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Self
from uuid import UUID

from sqlalchemy import text
from sqlmodel import Field, SQLModel

from contract import uuid7
from control_plane.db import current_session

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

UUIDV7_SHIM_DDL_V1 = (
    "CREATE FUNCTION uuidv7() RETURNS uuid LANGUAGE sql VOLATILE AS $$ "
    "SELECT encode(set_bit(set_bit(overlay(uuid_send(gen_random_uuid()) "
    "placing substring(int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3) FROM 1 FOR 6), "
    "52, 1), 53, 1), 'hex')::uuid $$"
)
"""A uuidv7() equivalent for Postgres 16 and 17, which predate the native function: millisecond
timestamp overlaid on gen_random_uuid with the version bits set to 7. Versioned and frozen like
the trigger DDL: the migrations import it, so its output can never change. Both schema paths
install it, the initial migration and test_schema's create_all."""


def needs_uuidv7_shim(connection: Connection) -> bool:
    """Whether the connected server predates the native uuidv7() the id default relies on."""
    version = connection.dialect.server_version_info or (0,)
    return version < (18,)


def uuid7_pk() -> Any:  # noqa: ANN401 mirrors sqlmodel.Field, whose Any return lets the FieldInfo assign to a typed column
    """Server-minted time-ordered primary key: uuid7 client-side so the id exists before the first
    flush (audit self-attribution depends on that), uuidv7() as the database backstop (native on
    Postgres 18, the shim above on 16 and 17)."""
    return Field(default_factory=uuid7, primary_key=True, sa_column_kwargs={"server_default": text("uuidv7()")})


class Identified(SQLModel):
    """Server-minted uuid7 primary key; models inherit the id and never declare it."""

    id: UUID = uuid7_pk()

    api_readonly: ClassVar[frozenset[str]] = frozenset({"id"})

    @classmethod
    async def find_by_id(cls, ident: UUID) -> Self | None:
        return await current_session().get(cls, ident)
