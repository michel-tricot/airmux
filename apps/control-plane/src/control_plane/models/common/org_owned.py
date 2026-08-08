from __future__ import annotations

from typing import ClassVar, Self
from uuid import UUID

from sqlmodel import SQLModel

from control_plane.db import current_session


class NotOwnedError(Exception):
    pass


class OrgOwned(SQLModel):
    org_id: UUID

    api_readonly: ClassVar[frozenset[str]] = frozenset({"org_id"})

    @classmethod
    async def owned_by(cls, org_id: UUID, ident: object) -> Self:
        record = await current_session().get(cls, ident)
        if record is None or record.org_id != org_id:
            raise NotOwnedError
        return record
