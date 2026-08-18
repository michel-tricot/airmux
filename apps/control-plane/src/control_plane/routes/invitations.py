from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import col

from control_plane.authority import ensure_org_role_change
from control_plane.authz import OrgRole, Permission
from control_plane.deps import ActorDep, OrgDep, org_scope, require
from control_plane.models import OrgInvitation, OrgMembership, User, Workspace
from control_plane.models.common.wire import Envelope
from control_plane.models.org_invitation import (
    InvitationUnavailableError,
    OrgInvitationCreate,
    OrgInvitationMintedOut,
    OrgInvitationOut,
    OrgInvitationRevokedOut,
)

router = APIRouter(prefix="/orgs/{org_id}/invitations")


def _out(invitation: OrgInvitation, now: datetime) -> OrgInvitationOut:
    return OrgInvitationOut.model_validate({**invitation.model_dump(), "status": invitation.status(now)})


def _minted(invitation: OrgInvitation, token: str, console_url: str, now: datetime) -> OrgInvitationMintedOut:
    url = f"{console_url.rstrip('/')}/invite#token={quote(token, safe='')}"
    return OrgInvitationMintedOut(invitation=_out(invitation, now), url=url)


@router.post("", tags=["Organization Invitations"], dependencies=[require(Permission.members_manage, org_scope)])
async def create_invitation(
    body: OrgInvitationCreate,
    org_id: OrgDep,
    actor: ActorDep,
    request: Request,
) -> Envelope[OrgInvitationMintedOut]:
    """Create an email-bound organization invitation and return its shareable URL once."""
    await ensure_org_role_change(actor, org_id, None, OrgRole(body.org_role))
    if body.workspace_id is not None:
        await Workspace.owned_by(org_id, body.workspace_id)
    user = await User.first(User.email == body.email)
    if user is not None and await OrgMembership.get((user.id, org_id)) is not None:
        raise HTTPException(status_code=409, detail="This account already belongs to the organization")
    if await OrgInvitation.active_for_email(org_id, body.email) is not None:
        raise HTTPException(status_code=409, detail="A pending invitation already exists for this email")
    now = datetime.now(tz=UTC)
    invitation, token = await OrgInvitation.issue(
        org_id=org_id,
        body=body,
        created_by_user_id=actor.principal_id,
        now=now,
    )
    return Envelope(data=_minted(invitation, token, request.app.state.settings.console_url, now))


@router.get("", tags=["Organization Invitations"], dependencies=[require(Permission.members_read, org_scope)])
async def list_invitations(org_id: OrgDep) -> Envelope[list[OrgInvitationOut]]:
    """List pending and expired invitations without returning their secret URLs."""
    invitations = await OrgInvitation.find(
        OrgInvitation.org_id == org_id,
        col(OrgInvitation.accepted_at).is_(None),
        col(OrgInvitation.revoked_at).is_(None),
        order_by=col(OrgInvitation.email),
    )
    now = datetime.now(tz=UTC)
    return Envelope(data=[_out(invitation, now) for invitation in invitations])


@router.post(
    "/{invitation_id}/reissue",
    tags=["Organization Invitations"],
    dependencies=[require(Permission.members_manage, org_scope)],
)
async def reissue_invitation(
    invitation_id: UUID,
    org_id: OrgDep,
    request: Request,
) -> Envelope[OrgInvitationMintedOut]:
    """Replace a pending or expired invitation URL and invalidate its previous secret."""
    invitation = await OrgInvitation.for_update(org_id, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    now = datetime.now(tz=UTC)
    try:
        token = await invitation.reissue(now)
    except InvitationUnavailableError as error:
        raise HTTPException(status_code=409, detail="Invitation can no longer be reissued") from error
    return Envelope(data=_minted(invitation, token, request.app.state.settings.console_url, now))


@router.post(
    "/{invitation_id}/revoke",
    tags=["Organization Invitations"],
    dependencies=[require(Permission.members_manage, org_scope)],
)
async def revoke_invitation(invitation_id: UUID, org_id: OrgDep) -> Envelope[OrgInvitationRevokedOut]:
    """Revoke an invitation without changing any membership already granted."""
    invitation = await OrgInvitation.for_update(org_id, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found")
    now = datetime.now(tz=UTC)
    try:
        await invitation.revoke(now)
    except InvitationUnavailableError as error:
        raise HTTPException(status_code=409, detail="Invitation can no longer be revoked") from error
    return Envelope(data=OrgInvitationRevokedOut(id=invitation.id, status="revoked", revoked_at=now))
