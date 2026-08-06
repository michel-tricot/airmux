from __future__ import annotations

from typing import ClassVar, Self

from sqlmodel import SQLModel

from control_plane.db import current_session


class NotOwnedError(Exception):
    pass


class OrgOwned(SQLModel):
    org_id: str

    api_readonly: ClassVar[frozenset[str]] = frozenset({"org_id"})

    @classmethod
    async def owned_by(cls, org: str, ident: object) -> Self:
        row = await current_session().get(cls, ident)
        if row is None or row.org_id != org:
            raise NotOwnedError
        return row
