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
from control_plane.models.inference_key import InferenceKey
from control_plane.models.workspace_membership import WorkspaceMembership


@audited
class Workspace(Record, Identified, OrgOwned, Tombstonable, table=True):
    """The scope inference keys live in; membership is drawn from the owning org.

    The (id, org_id) unique constraint exists only as the composite foreign key target that
    keeps workspace-scoped rows structurally inside the workspace's org.
    """

    __table_args__: ClassVar = (UniqueConstraint("id", "org_id", name="workspace_id_org_id_key"),)

    org_id: UUID = Field(foreign_key="org.id")
    name: str

    async def delete_with_contents(self) -> None:
        """Delete the workspace with the rows scoped to it: its inference keys and its members.

        A workspace's keys cannot outlive it, so revoked and live ones go together. The usage it
        recorded is history rather than a scoped row, and stays.
        """
        for key in await InferenceKey.find(InferenceKey.workspace_id == self.id):
            await key.delete()
        for membership in await WorkspaceMembership.find(WorkspaceMembership.workspace_id == self.id):
            await membership.delete()
        await self.delete()


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
