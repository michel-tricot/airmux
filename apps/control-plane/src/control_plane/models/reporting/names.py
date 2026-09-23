from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy import select as sql_select
from sqlmodel import col

from control_plane.models.inference_key import InferenceKey
from control_plane.models.org_membership import OrgMembership
from control_plane.models.provider_credential import ProviderCredential
from control_plane.models.user import User
from control_plane.models.workspace import Workspace
from control_plane.models.workspace_membership import WorkspaceMembership

if TYPE_CHECKING:
    from control_plane.models.reporting.query import Grouping


async def names_for_dimension(org_id: UUID, workspace_id: UUID | None, dimension: Grouping, identifiers: list[str]) -> dict[str, str]:
    if dimension in {"model", "provider"}:
        return {}
    uuids = []
    for identifier in identifiers:
        try:
            uuids.append(UUID(identifier))
        except ValueError:
            continue
    if not uuids:
        return {}
    if dimension == "workspace":
        workspaces = await Workspace.find(col(Workspace.org_id) == org_id, col(Workspace.id).in_(uuids))
        return {str(workspace.id): workspace.name for workspace in workspaces}
    if dimension == "owner":
        member_ids = (
            sql_select(col(WorkspaceMembership.user_id)).where(col(WorkspaceMembership.workspace_id) == workspace_id)
            if workspace_id is not None
            else sql_select(col(OrgMembership.user_id)).where(col(OrgMembership.org_id) == org_id)
        )
        users = await User.find(col(User.id).in_(uuids), col(User.id).in_(member_ids))
        return {str(user.id): user.email for user in users}
    if dimension == "key":
        keys = await InferenceKey.find(col(InferenceKey.org_id) == org_id, col(InferenceKey.id).in_(uuids))
        return {str(key.id): key.label for key in keys}
    conditions = [col(ProviderCredential.id).in_(uuids), or_(col(ProviderCredential.org_id) == org_id, col(ProviderCredential.org_id).is_(None))]
    if workspace_id is not None:
        conditions.append(or_(col(ProviderCredential.workspace_id) == workspace_id, col(ProviderCredential.workspace_id).is_(None)))
    credentials = await ProviderCredential.find(*conditions)
    return {str(credential.id): credential.name for credential in credentials}
