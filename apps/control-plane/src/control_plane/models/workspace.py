from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.common import Identified, OrgOwned, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordCreate, RecordOut, RecordUpdate


@audited
class Workspace(Record, Identified, OrgOwned, Tombstonable, table=True):
    """The scope inference keys live in; membership is drawn from the owning org.

    The (id, org_id) unique constraint exists only as the composite foreign key target that
    keeps workspace-scoped rows structurally inside the workspace's org.
    """

    __table_args__: ClassVar = (UniqueConstraint("id", "org_id", name="workspace_id_org_id_key"),)

    org_id: UUID = Field(foreign_key="org.id")
    name: str


class WorkspaceCreate(RecordCreate[Workspace]):
    name: str = Field(description="Workspace name, e.g. staging")


class WorkspaceUpdate(RecordUpdate[Workspace]):
    name: str | None = None


class WorkspaceOut(RecordOut[Workspace]):
    id: UUID
    org_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
