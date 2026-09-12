from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, func
from sqlmodel import Field, col, select

from control_plane.authz import ALL_PERMISSIONS, Actor, Grant, Permission, Scope
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

    async def authorized_until(self, now: datetime) -> datetime | None:
        from control_plane.authority import is_allowed  # noqa: PLC0415 authority depends on the complete model graph
        from control_plane.models.auth_session import AuthSession  # noqa: PLC0415 session lifecycle depends on playground sessions
        from control_plane.models.management_key import ManagementKey  # noqa: PLC0415 key lifecycle depends on playground sessions

        key = await ManagementKey.find_by_id(self.credential_id)
        expiry = self.expires_at
        if key is not None:
            if key.user_id != self.user_id:
                return None
            permissions = frozenset(key.permissions)
            scope = key.scope
            seen: set[UUID] = set()
            while key is not None:
                if key.id in seen or key.status(now) != "active" or not key.scope.covers(Scope.workspace(self.org_id, self.workspace_id)):
                    return None
                seen.add(key.id)
                permissions &= frozenset(key.permissions)
                if key.expires_at is not None:
                    expiry = min(expiry, key.expires_at)
                if key.parent_id is None:
                    break
                key = await ManagementKey.find_by_id(key.parent_id)
                if key is None:
                    return None
            actor = Actor(
                credential_id=self.credential_id,
                principal_id=self.user_id,
                credential_kind="management_key",
                grant=Grant(scope=scope, permissions=permissions),
            )
        else:
            auth_session = await AuthSession.find_by_id(self.credential_id)
            if auth_session is None or auth_session.user_id != self.user_id:
                return None
            expiry = min(expiry, auth_session.expires_at, auth_session.absolute_expires_at)
            actor = Actor(
                credential_id=self.credential_id,
                principal_id=self.user_id,
                credential_kind="session",
                grant=Grant(scope=Scope.instance(), permissions=ALL_PERMISSIONS),
            )
        if expiry <= now or not await is_allowed(actor, Permission.playground_execute, Scope.workspace(self.org_id, self.workspace_id)):
            return None
        return expiry

    @classmethod
    async def revoke_unsupported(cls, user_id: UUID | None = None, *, credential_ids: frozenset[UUID] | None = None) -> None:
        now = datetime.now(tz=UTC)
        conditions = (cls.user_id == user_id,) if user_id is not None else ()
        if credential_ids is not None:
            conditions += (col(cls.credential_id).in_(credential_ids),)
        for playground_session in await cls.find(col(cls.revoked).is_(False), *conditions):
            expiry = await playground_session.authorized_until(now)
            if expiry is None:
                playground_session.revoked = True
                await playground_session.save()
            elif expiry < playground_session.expires_at:
                playground_session.expires_at = expiry
                await playground_session.save()

    @classmethod
    async def revoke_credential(cls, credential_id: UUID) -> None:
        playground_session = await cls.by_credential(credential_id)
        if playground_session is not None and not playground_session.revoked:
            playground_session.revoked = True
            await playground_session.save()

    @classmethod
    async def revoke_user(cls, user_id: UUID) -> None:
        for playground_session in await cls.find(cls.user_id == user_id, col(cls.revoked).is_(False)):
            playground_session.revoked = True
            await playground_session.save()


class PlaygroundSessionReadyOut(BaseModel):
    id: UUID
    expires_at: datetime
    status: Literal["ready"]


class PlaygroundSessionEndedOut(BaseModel):
    status: Literal["ended"]
