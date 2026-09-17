from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, func
from sqlmodel import Field, col, select

from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.bundle_input import bundle_input
from control_plane.models.common import Identified, OrgOwned, Tombstonable, UTCDateTime
from control_plane.models.common.base import Record


@audited
@bundle_input(scope="org")
class PlaygroundSession(Record, Identified, OrgOwned, Tombstonable, table=True):
    __table_args__: ClassVar = (
        ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"], ondelete="CASCADE"),
        UniqueConstraint("credential_id", name="playground_session_credential_id_key"),
    )

    org_id: UUID = Field(foreign_key="org.id", ondelete="CASCADE")
    workspace_id: UUID
    user_id: UUID = Field(foreign_key="user.id", ondelete="CASCADE")
    credential_id: UUID
    token_hash: str = Field(unique=True)
    expires_at: datetime = Field(sa_type=UTCDateTime)
    revoked: bool = False

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})

    @classmethod
    async def by_credential(cls, credential_id: UUID) -> PlaygroundSession | None:
        return await cls.first(cls.credential_id == credential_id)

    @classmethod
    async def for_rotation(cls, credential_id: UUID) -> PlaygroundSession | None:
        lock_id = int.from_bytes(credential_id.bytes[:8], signed=True)
        await current_session().execute(select(func.pg_advisory_xact_lock(lock_id)))
        return await cls.by_credential(credential_id)

    @classmethod
    async def by_token(cls, credential_id: UUID, hashed_token: str) -> PlaygroundSession | None:
        return await cls.first(cls.credential_id == credential_id, cls.token_hash == hashed_token)

    @classmethod
    async def revoke_owned_in_workspace(cls, user_id: UUID, workspace_id: UUID) -> None:
        for playground_session in await cls.find(
            cls.user_id == user_id,
            cls.workspace_id == workspace_id,
            col(cls.revoked).is_(False),
        ):
            playground_session.revoked = True
            await playground_session.save()

    @classmethod
    async def revoke_owned_in_org(cls, user_id: UUID, org_id: UUID) -> None:
        for playground_session in await cls.find(cls.user_id == user_id, cls.org_id == org_id, col(cls.revoked).is_(False)):
            playground_session.revoked = True
            await playground_session.save()

    @classmethod
    async def delete_owned_by(cls, user_id: UUID) -> None:
        for playground_session in await cls.find(cls.user_id == user_id):
            await playground_session.delete()

    def active(self, now: datetime) -> bool:
        return not self.revoked and self.expires_at > now


class PlaygroundSessionReadyOut(BaseModel):
    id: UUID
    expires_at: datetime
    status: Literal["ready"]


class PlaygroundSessionEndedOut(BaseModel):
    status: Literal["ended"]
