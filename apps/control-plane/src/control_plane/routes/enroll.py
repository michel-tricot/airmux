from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from control_plane.authz import Actor, OrgRole, ScopeLevel
from control_plane.deps import ActingUserDep, ActorDep, CookieUserDep, browser_scoped, public, user_scoped
from control_plane.models import Org, OrgInvitation, OrgMembership
from control_plane.models.common import PageDep  # noqa: TC001 FastAPI resolves route annotations at runtime
from control_plane.models.common.wire import Envelope, PageEnvelope
from control_plane.models.org import OrgCreate, OrgOut
from control_plane.models.org_invitation import (
    InvitationAcceptedOut,
    InvitationEmailMismatchError,
    InvitationPreviewOut,
    InvitationTokenIn,
    InvitationUnavailableError,
)

router = APIRouter(prefix="/enroll")


class EnrollOut(BaseModel):
    personal_org_id: UUID | None
    org_count: int
    pending_invitation_count: int


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


def _visible_org_id(actor: Actor) -> UUID | None:
    return actor.grant.scope.org_id if actor.grant.scope.level in {ScopeLevel.org, ScopeLevel.workspace} else None


@router.get("", tags=["Enrollment"], dependencies=[user_scoped("api")])
async def enrollment(user: ActingUserDep, actor: ActorDep) -> Envelope[EnrollOut]:
    """Summarize the current user's visible organizations and pending invitations."""
    now = datetime.now(tz=UTC)
    visible_org_id = _visible_org_id(actor)
    personal = await Org.personal_of(user.id)
    personal_visible = personal is not None and (visible_org_id is None or personal.id == visible_org_id)
    return Envelope(
        data=EnrollOut(
            personal_org_id=personal.id if personal_visible and personal else None,
            org_count=await Org.count_joined_by(user.id, visible_org_id),
            pending_invitation_count=await OrgInvitation.count_pending_for_email(user.email, now, actor.grant.scope),
        )
    )


@router.get("/organizations", tags=["Enrollment"], dependencies=[user_scoped("api")])
async def list_enrollment_orgs(user: ActingUserDep, actor: ActorDep, page: PageDep) -> PageEnvelope[OrgOut]:
    """List the current user's visible organizations."""
    return PageEnvelope.from_slice(await Org.page_joined_by(user.id, _visible_org_id(actor), page), OrgOut)


@router.get("/invitations", tags=["Enrollment"], dependencies=[user_scoped("api")])
async def list_enrollment_invitations(user: ActingUserDep, actor: ActorDep, page: PageDep) -> PageEnvelope[InvitationPreviewOut]:
    """List pending invitations visible to the current user."""
    invitations = await OrgInvitation.page_pending_for_email(user.email, datetime.now(tz=UTC), actor.grant.scope, page)
    names = await OrgInvitation.preview_names(tuple(invitation.id for invitation in invitations.items))
    return PageEnvelope.from_slice(invitations.map(lambda invitation: _invitation_preview(invitation, *names[invitation.id])))


@router.post("/org", tags=["Enrollment"], dependencies=[browser_scoped("api")])
async def create_personal_org(body: OrgCreate, user: CookieUserDep) -> Envelope[OrgOut]:
    """Create the current user's personal organization and make them its owner.

    A user can own one personal organization at a time. Deleting it allows another to be created.
    """
    if await Org.personal_of(user.id) is not None:
        raise HTTPException(status_code=409, detail="personal org already exists")
    org = await Org.create(body.name, body.slug, personal_for=user.id)
    await OrgMembership(user_id=user.id, org_id=org.id, role=OrgRole.owner).save()
    return Envelope(data=OrgOut.model_validate(org))


@router.post("/invitations/preview", tags=["Enrollment"], dependencies=[public("api")])
async def preview_invitation(body: InvitationTokenIn) -> Envelope[InvitationPreviewOut]:
    """Preview the organization and optional workspace named by a shared invitation secret."""
    preview = await OrgInvitation.preview_for_token(body.token)
    if preview is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    invitation, org_name, workspace_name = preview
    if invitation.status(datetime.now(tz=UTC)) != "pending":
        raise HTTPException(status_code=410, detail="Invitation is no longer available")
    return Envelope(data=_invitation_preview(invitation, org_name, workspace_name))


@router.post("/invitations/accept", tags=["Enrollment"], dependencies=[browser_scoped("api")])
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
