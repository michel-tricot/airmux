from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import ForeignKeyConstraint, Index
from sqlmodel import Field, col

from control_plane.models.audit import audited
from control_plane.models.common import Identified, NotOwnedError, OrgOwned, PageQuery, PageSlice, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordOut, RequestModel
from control_plane.models.runtime_configuration import bundle_input


@audited
@bundle_input(scope="org", columns=("org_id", "workspace_id", "user_id", "token_hash", "revoked"))
class InferenceKey(Record, Identified, OrgOwned, Tombstonable, table=True):
    """org_id stays denormalized beside workspace_id so the compiler collects an org's keys in one
    query and owned_by keeps working; the composite foreign key keeps the pair from disagreeing."""

    __table_args__: ClassVar = (
        ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"]),
        Index("inference_key_workspace_id_idx", "workspace_id", "id"),
    )

    org_id: UUID = Field(foreign_key="org.id")
    workspace_id: UUID
    user_id: UUID = Field(foreign_key="user.id")
    token_hash: str = Field(unique=True)
    prefix: str
    revoked: bool = False
    label: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})
    api_readonly: ClassVar[frozenset[str]] = frozenset({"workspace_id", "user_id", "revoked", "label", "prefix"})

    @classmethod
    async def in_workspace(cls, org_id: UUID, workspace_id: UUID, key_id: UUID) -> Self:
        key = await cls.owned_by(org_id, key_id)
        if key.workspace_id != workspace_id:
            raise NotOwnedError
        return key

    @classmethod
    async def revoke_owned_in_workspace(cls, user_id: UUID, workspace_id: UUID) -> None:
        for key in await cls.find(cls.user_id == user_id, cls.workspace_id == workspace_id, col(cls.revoked).is_(False)):
            key.revoked = True
            await key.save()

    @classmethod
    async def revoke_owned_in_org(cls, user_id: UUID, org_id: UUID) -> None:
        for key in await cls.find(cls.user_id == user_id, cls.org_id == org_id, col(cls.revoked).is_(False)):
            key.revoked = True
            await key.save()

    @classmethod
    async def delete_owned_by(cls, user_id: UUID) -> None:
        for key in await cls.find(cls.user_id == user_id):
            await key.delete()

    @classmethod
    async def page_for_workspace(cls, workspace_id: UUID, request: PageQuery) -> PageSlice[Self]:
        return await cls.page(request, partition={"workspace_id": workspace_id})


class InferenceKeyIn(RequestModel):
    label: str = Field(description="What this key is for, e.g. staging or the calling app; shown in listings", min_length=1, max_length=80)
    user_id: UUID = Field(description="Principal whose identity this key carries into policy evaluation")


class InferenceKeyOwnerOut(BaseModel):
    user_id: UUID
    email: str
    name: str
    service_account: bool


class InferenceKeyOut(RecordOut[InferenceKey]):
    id: UUID
    org_id: UUID
    workspace_id: UUID
    user_id: UUID
    revoked: bool
    label: str
    prefix: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class InferenceKeyCreatedOut(BaseModel):
    id: UUID
    token: str


class InferenceKeyRevokedOut(BaseModel):
    id: UUID
    status: Literal["revoked"]
