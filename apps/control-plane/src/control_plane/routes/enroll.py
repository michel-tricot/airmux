from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from control_plane.authority import visible_org_ids
from control_plane.authz import OrgRole
from control_plane.deps import ActingUserDep, ActorDep, CookieUserDep, browser_scoped, public, user_scoped
from control_plane.models import Org, OrgInvitation, OrgMembership
from control_plane.models.common.wire import Envelope
from control_plane.models.org import OrgCreate, OrgOut, OrgSlugTakenError
from control_plane.models.org_invitation import (
    InvitationAcceptedOut,
    InvitationEmailMismatchError,
    InvitationPreviewOut,
    InvitationTokenIn,
    InvitationUnavailableError,
)

router = APIRouter(prefix="/enroll")


class EnrollOut(BaseModel):
    orgs: list[OrgOut]
    personal_org_id: UUID | None
    pending_invitations: list[InvitationPreviewOut]


def _invitation_preview(invitation: OrgInvitation, org_name: str, workspace_name: str | None) -> InvitationPreviewOut:
    return InvitationPreviewOut(
        email=invitation.email,
        org_id=invitation.org_id,
        org_name=org_name,
        org_role=invitation.org_role,
        workspace_id=invitation.workspace_id,
        workspace_name=workspace_name,
        workspace_role=invitation.workspace_role,
        expires_at=invitation.expires_at,
    )


@router.get("", tags=["Enrollment"], dependencies=[user_scoped()])
async def enrollment(user: ActingUserDep, actor: ActorDep) -> Envelope[EnrollOut]:
    """List the current user's visible organizations, personal organization, and pending invitations."""
    orgs = await Org.joined_by(user.id)
    visible = frozenset(visible_org_ids(actor, (org.id for org in orgs)))
    orgs = [org for org in orgs if org.id in visible]
    personal = await Org.personal_of(user.id)
    personal_visible = personal is not None and bool(visible_org_ids(actor, (personal.id,)))
    invitations = await OrgInvitation.pending_for_email(user.email, datetime.now(tz=UTC), actor.grant.scope)
    return Envelope(
        data=EnrollOut(
            orgs=[OrgOut.model_validate(org) for org in orgs],
            personal_org_id=personal.id if personal_visible and personal else None,
            pending_invitations=[_invitation_preview(invitation, org_name, workspace_name) for invitation, org_name, workspace_name in invitations],
        )
    )


@router.post("/org", tags=["Enrollment"], dependencies=[browser_scoped()])
async def create_personal_org(body: OrgCreate, user: CookieUserDep) -> Envelope[OrgOut]:
    """Create the current user's personal organization and make them its owner.

    A user can own one personal organization at a time. Deleting it allows another to be created.
    """
    if await Org.personal_of(user.id) is not None:
        raise HTTPException(status_code=409, detail="personal org already exists")
    try:
        org = await Org.create(body.name, body.slug, personal_for=user.id)
    except OrgSlugTakenError as error:
        raise HTTPException(status_code=409, detail="slug is already taken") from error
    await OrgMembership(user_id=user.id, org_id=org.id, role=OrgRole.owner).save()
    return Envelope(data=OrgOut.model_validate(org))


@router.post("/invitations/preview", tags=["Enrollment"], dependencies=[public()])
async def preview_invitation(body: InvitationTokenIn) -> Envelope[InvitationPreviewOut]:
    """Preview the organization and optional workspace named by a shared invitation secret."""
    preview = await OrgInvitation.preview_for_token(body.token)
    if preview is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    invitation, org_name, workspace_name = preview
    if invitation.status(datetime.now(tz=UTC)) != "pending":
        raise HTTPException(status_code=410, detail="Invitation is no longer available")
    return Envelope(data=_invitation_preview(invitation, org_name, workspace_name))


@router.post("/invitations/accept", tags=["Enrollment"], dependencies=[browser_scoped()])
async def accept_invitation(body: InvitationTokenIn, user: CookieUserDep) -> Envelope[InvitationAcceptedOut]:
    """Accept an invitation whose email matches the signed-in human account."""
    invitation = await OrgInvitation.for_token(body.token, lock=True)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    try:
        await invitation.accept(user, datetime.now(tz=UTC))
    except InvitationEmailMismatchError as error:
        raise HTTPException(status_code=403, detail="Invitation email does not match the signed-in account") from error
    except InvitationUnavailableError as error:
        raise HTTPException(status_code=410, detail="Invitation is no longer available") from error
    return Envelope(
        data=InvitationAcceptedOut(
            invitation_id=invitation.id,
            org_id=invitation.org_id,
            workspace_id=invitation.workspace_id,
            status="accepted",
        )
    )
