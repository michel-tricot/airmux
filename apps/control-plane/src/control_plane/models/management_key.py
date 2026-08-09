from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import JSON
from sqlmodel import Field, col

from control_plane.authz import Scope
from control_plane.models.audit import audited
from control_plane.models.common import Identified, OrgOwned, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordOut


@audited
class ManagementKey(Record, Identified, OrgOwned, Tombstonable, table=True):
    """A user's bearer credential for one org.

    org_id is mandatory, which is what makes owned_by the lookup for every org-scoped route: the key
    belongs to exactly one org, and no management key can express instance scope by omitting it.
    """

    org_id: UUID = Field(foreign_key="org.id")
    user_id: UUID = Field(foreign_key="user.id")
    token_hash: str = Field(unique=True)
    prefix: str
    revoked: bool = False
    scopes: list[str] | None = Field(default=None, sa_type=JSON)
    label: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"token_hash"})
    api_readonly: ClassVar[frozenset[str]] = frozenset({"scopes", "label", "prefix"})

    @classmethod
    async def retire_for_client(cls, user_id: UUID, org_id: UUID, label: str) -> list[Self]:
        """Revoke the live keys this client label holds for the org, so a re-login replaces its key instead of accumulating.

        The live filter belongs in the query, not in Python: already-revoked keys are not rows this
        needs to read. The writes stay one per key because that is what the model API expresses, and
        a client label holds one live key in the ordinary case.
        """
        keys = await cls.find(cls.user_id == user_id, cls.org_id == org_id, cls.label == label, col(cls.revoked).is_(False))
        for key in keys:
            key.revoked = True
            await key.save()
        return keys


class ManagementKeyOut(RecordOut[ManagementKey]):
    id: UUID
    org_id: UUID
    user_id: UUID
    revoked: bool
    scopes: list[str] | None
    label: str
    prefix: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ManagementKeyMintedOut(BaseModel):
    id: UUID
    org_id: UUID
    user_id: UUID
    scopes: list[str] | None
    label: str
    token: str


class ManagementKeyRevokedOut(BaseModel):
    id: UUID
    status: Literal["revoked"]


class ManagementKeyIn(BaseModel):
    label: str = Field(description="Where this key lives, e.g. ci or laptop; shown in listings", min_length=1, max_length=80)
    user_id: UUID | None = Field(None, description="User the key is minted for; defaults to the acting user")
    scopes: list[Scope] | None = Field(None, description="Restrict the key to these scopes; omit for the user's full authority")
