from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, func
from sqlmodel import Field, select

from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.common import Identified, OrgOwned, Tombstonable, UTCDateTime
from control_plane.models.common.base import Record
from control_plane.models.runtime_configuration import bundle_input


@audited
@bundle_input(scope="org", columns=("org_id", "workspace_id", "token_hash", "expires_at", "revoked"))
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

    def active(self, now: datetime) -> bool:
        return not self.revoked and self.expires_at > now


class PlaygroundSessionReadyOut(BaseModel):
    id: UUID
    expires_at: datetime
    status: Literal["ready"]


class PlaygroundSessionEndedOut(BaseModel):
    status: Literal["ended"]
