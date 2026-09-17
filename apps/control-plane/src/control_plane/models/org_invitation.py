from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator
from pydantic import Field as PydanticField
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, func, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlmodel import Field, col, select

from contract import token_hash
from control_plane.authz import Scope, ScopeLevel
from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.common import Identified, OrgOwned, PageQuery, PageSlice, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordCreate, RecordOut, RequestModel
from control_plane.models.org import Org
from control_plane.models.org_membership import OrgMembership
from control_plane.models.user import User
from control_plane.models.workspace import Workspace
from control_plane.models.workspace_membership import WorkspaceMembership

INVITATION_TOKEN_PREFIX = "invite_"  # noqa: S105 token discriminator, not a secret
INVITATION_TTL = timedelta(days=7)
InvitationStatus = Literal["pending", "expired", "accepted", "revoked"]


class InvitationUnavailableError(RuntimeError):
    pass


class InvitationEmailMismatchError(RuntimeError):
    pass


def _new_token() -> str:
    return INVITATION_TOKEN_PREFIX + secrets.token_urlsafe(32)


@audited
class OrgInvitation(Record, Identified, OrgOwned, Tombstonable, table=True):
    __table_args__: ClassVar = (
        CheckConstraint("org_role IN ('admin', 'member')", name="org_invitation_org_role_valid"),
        CheckConstraint(
            "workspace_role IS NULL OR workspace_role IN ('admin', 'member', 'viewer')",
            name="org_invitation_workspace_role_valid",
        ),
        CheckConstraint(
            "(workspace_id IS NULL) = (workspace_role IS NULL)",
            name="org_invitation_workspace_grant_complete",
        ),
        CheckConstraint(
            "accepted_at IS NULL OR revoked_at IS NULL",
            name="org_invitation_not_accepted_and_revoked",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "org_id"],
            ["workspace.id", "workspace.org_id"],
            ondelete="CASCADE",
        ),
        Index(
            "org_invitation_pending_org_email_key",
            "org_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
        Index(
            "org_invitation_pending_org_id_idx",
            "org_id",
            "id",
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
        Index(
            "org_invitation_pending_email_id_idx",
            "email",
            "id",
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
        Index(
            "org_invitation_pending_email_org_id_idx",
            "email",
            "org_id",
            "id",
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
        Index(
            "org_invitation_pending_email_org_workspace_id_idx",
            "email",
            "org_id",
            "workspace_id",
            "id",
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    org_id: UUID = Field(foreign_key="org.id", ondelete="CASCADE")
    email: str = Field(sa_type=CITEXT)
    org_role: str
    workspace_id: UUID | None = None
    workspace_role: str | None = None
    token_hash: str = Field(unique=True)
    created_by_user_id: UUID | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")
    expires_at: datetime = Field(sa_type=UTCDateTime)
    accepted_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    accepted_by_user_id: UUID | None = Field(default=None, foreign_key="user.id", ondelete="SET NULL")
    revoked_at: datetime | None = Field(default=None, sa_type=UTCDateTime)

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})
    api_readonly: ClassVar[frozenset[str]] = frozenset({"created_by_user_id", "expires_at", "accepted_at", "accepted_by_user_id", "revoked_at"})
    api_immutable: ClassVar[frozenset[str]] = frozenset({"email", "org_role", "workspace_id", "workspace_role"})

    @classmethod
    async def issue(
        cls,
        *,
        org_id: UUID,
        body: OrgInvitationCreate,
        created_by_user_id: UUID,
        now: datetime,
    ) -> tuple[Self, str]:
        token = _new_token()
        invitation = await cls(
            org_id=org_id,
            email=body.email,
            org_role=body.org_role,
            workspace_id=body.workspace_id,
            workspace_role=body.workspace_role,
            token_hash=token_hash(token),
            created_by_user_id=created_by_user_id,
            expires_at=now + INVITATION_TTL,
        ).save()
        return invitation, token

    @classmethod
    async def active_for_email(cls, org_id: UUID, email: str) -> Self | None:
        return await cls.first(
            cls.org_id == org_id,
            cls.email == User.normalize_email(email),
            col(cls.accepted_at).is_(None),
            col(cls.revoked_at).is_(None),
        )

    @classmethod
    async def page_for_org(cls, org_id: UUID, request: PageQuery) -> PageSlice[Self]:
        return await cls.page(
            request,
            col(cls.accepted_at).is_(None),
            col(cls.revoked_at).is_(None),
            partition={"org_id": org_id},
        )

    @classmethod
    async def pending_for_email(cls, email: str, now: datetime, scope: Scope) -> list[tuple[Self, str, str | None]]:
        query = (
            select(cls, Org.name, Workspace.name)
            .join(Org, col(Org.id) == col(cls.org_id))
            .outerjoin(Workspace, col(Workspace.id) == col(cls.workspace_id))
            .where(
                cls.email == User.normalize_email(email),
                col(cls.accepted_at).is_(None),
                col(cls.revoked_at).is_(None),
                col(cls.expires_at) > now,
            )
            .order_by(col(cls.created_at), col(cls.id))
        )
        if scope.level is not ScopeLevel.instance:
            query = query.where(cls.org_id == scope.org_id)
        if scope.level is ScopeLevel.workspace:
            query = query.where(cls.workspace_id == scope.workspace_id)
        return [(result[0], result[1], result[2]) for result in (await current_session().execute(query)).all()]

    @classmethod
    async def page_pending_for_email(cls, email: str, now: datetime, scope: Scope, request: PageQuery) -> PageSlice[Self]:
        normalized_email = User.normalize_email(email)
        conditions = [
            col(cls.accepted_at).is_(None),
            col(cls.revoked_at).is_(None),
            col(cls.expires_at) > now,
        ]
        partition: dict[str, str | UUID | None] = {"email": normalized_email}
        if scope.level is not ScopeLevel.instance:
            partition["org_id"] = scope.org_id
        if scope.level is ScopeLevel.workspace:
            partition["workspace_id"] = scope.workspace_id
        return await cls.page(
            request,
            *conditions,
            partition=partition,
        )

    @classmethod
    async def count_pending_for_email(cls, email: str, now: datetime, scope: Scope) -> int:
        statement = (
            select(func.count())
            .select_from(cls)
            .where(
                cls.email == User.normalize_email(email),
                col(cls.accepted_at).is_(None),
                col(cls.revoked_at).is_(None),
                col(cls.expires_at) > now,
            )
        )
        if scope.level is not ScopeLevel.instance:
            statement = statement.where(cls.org_id == scope.org_id)
        if scope.level is ScopeLevel.workspace:
            statement = statement.where(cls.workspace_id == scope.workspace_id)
        return (await current_session().execute(statement)).scalar_one()

    @classmethod
    async def preview_names(cls, invitation_ids: tuple[UUID, ...]) -> dict[UUID, tuple[str, str | None]]:
        if not invitation_ids:
            return {}
        query = (
            select(cls.id, Org.name, Workspace.name)
            .join(Org, col(Org.id) == col(cls.org_id))
            .outerjoin(Workspace, col(Workspace.id) == col(cls.workspace_id))
            .where(col(cls.id).in_(invitation_ids))
        )
        return {result[0]: (result[1], result[2]) for result in (await current_session().execute(query)).all()}

    @classmethod
    async def for_token(cls, token: str, *, lock: bool = False) -> Self | None:
        if not token.startswith(INVITATION_TOKEN_PREFIX):
            return None
        query = select(cls).where(cls.token_hash == token_hash(token))
        if lock:
            query = query.with_for_update()
        return (await current_session().execute(query)).scalar_one_or_none()

    @classmethod
    async def preview_for_token(cls, token: str) -> tuple[Self, str, str | None] | None:
        if not token.startswith(INVITATION_TOKEN_PREFIX):
            return None
        query = (
            select(cls, Org.name, Workspace.name)
            .join(Org, col(Org.id) == col(cls.org_id))
            .outerjoin(Workspace, col(Workspace.id) == col(cls.workspace_id))
            .where(cls.token_hash == token_hash(token))
        )
        result = (await current_session().execute(query)).one_or_none()
        return None if result is None else (result[0], result[1], result[2])

    @classmethod
    async def for_update(cls, org_id: UUID, invitation_id: UUID) -> Self | None:
        query = select(cls).where(cls.id == invitation_id, cls.org_id == org_id).with_for_update()
        return (await current_session().execute(query)).scalar_one_or_none()

    def status(self, now: datetime) -> InvitationStatus:
        if self.accepted_at is not None:
            return "accepted"
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at <= now:
            return "expired"
        return "pending"

    async def reissue(self, now: datetime) -> str:
        if self.accepted_at is not None or self.revoked_at is not None:
            raise InvitationUnavailableError
        token = _new_token()
        self.token_hash = token_hash(token)
        self.expires_at = now + INVITATION_TTL
        await self.save()
        return token

    async def revoke(self, now: datetime) -> None:
        if self.accepted_at is not None or self.revoked_at is not None:
            raise InvitationUnavailableError
        self.revoked_at = now
        await self.save()

    def require_available_for_email(self, email: str, now: datetime) -> None:
        if self.accepted_at is not None or self.revoked_at is not None or self.expires_at <= now:
            raise InvitationUnavailableError
        if self.email != User.normalize_email(email):
            raise InvitationEmailMismatchError

    async def accept(self, user: User, now: datetime) -> Self:
        if self.accepted_at is not None:
            if self.accepted_by_user_id == user.id and self.email == User.normalize_email(user.email):
                return self
            raise InvitationUnavailableError
        self.require_available_for_email(user.email, now)
        await OrgMembership.ensure(user_id=user.id, org_id=self.org_id, role=self.org_role)
        if self.workspace_id is not None and self.workspace_role is not None:
            await WorkspaceMembership.ensure(
                user_id=user.id,
                workspace_id=self.workspace_id,
                org_id=self.org_id,
                role=self.workspace_role,
            )
        self.accepted_at = now
        self.accepted_by_user_id = user.id
        return await self.save()


class OrgInvitationCreate(RecordCreate[OrgInvitation]):
    email: str = PydanticField(description="Email address that must match the account accepting the invitation", min_length=3, max_length=320)
    org_role: str = PydanticField(description="Organization role to grant", pattern="^(admin|member)$")
    workspace_id: UUID | None = PydanticField(default=None, description="Optional workspace to join")
    workspace_role: str | None = PydanticField(
        default=None,
        description="Role to grant in the selected workspace",
        pattern="^(admin|member|viewer)$",
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, email: str) -> str:
        return User.normalize_email(email)

    @model_validator(mode="after")
    def complete_workspace_grant(self) -> Self:
        if (self.workspace_id is None) != (self.workspace_role is None):
            msg = "workspace_id and workspace_role must be provided together"
            raise ValueError(msg)
        return self


class OrgInvitationOut(RecordOut[OrgInvitation]):
    id: UUID
    org_id: UUID
    email: str
    org_role: str
    workspace_id: UUID | None
    workspace_role: str | None
    created_by_user_id: UUID | None
    expires_at: datetime
    accepted_at: datetime | None
    accepted_by_user_id: UUID | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    status: InvitationStatus

    api_extra: ClassVar[frozenset[str]] = frozenset({"status"})


class OrgInvitationMintedOut(BaseModel):
    invitation: OrgInvitationOut
    url: str


class OrgInvitationRevokedOut(BaseModel):
    id: UUID
    status: Literal["revoked"]
    revoked_at: datetime


class InvitationTokenIn(RequestModel):
    token: str = PydanticField(description="Secret from the shared invitation link", min_length=1, max_length=256)


class InvitationPreviewOut(BaseModel):
    email: str
    org_id: UUID
    org_name: str
    org_role: str
    workspace_id: UUID | None
    workspace_name: str | None
    workspace_role: str | None
    expires_at: datetime


class InvitationAcceptedOut(BaseModel):
    invitation_id: UUID
    org_id: UUID
    workspace_id: UUID | None
    status: Literal["accepted"]
