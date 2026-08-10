from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import col

from contract import uuid7
from control_plane.authz import Scope
from control_plane.compiler import UnknownOrgError, compile_and_store
from control_plane.deps import MgmtDep, OrgDep, require
from control_plane.keys import mint_management_key
from control_plane.models import AuditLog, Bundle, ManagementKey, OrgMembership, UsageEvent, User
from control_plane.models.audit import ActivityOut
from control_plane.models.bundle import BundleOut
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.management_key import ManagementKeyIn, ManagementKeyMintedOut, ManagementKeyOut, ManagementKeyRevokedOut
from control_plane.models.org_membership import MembershipOut, OrgMemberOut
from control_plane.models.usage_event import UsageEventOut

router = APIRouter(prefix="/org")


@router.get("/users", tags=["Org Users"], dependencies=[require(Scope.users_read)])
async def list_org_users(org_id: OrgDep) -> Envelope[list[OrgMemberOut]]:
    """The acting org's members; an org credential sees its own roster, never the instance's."""
    members = await User.members_of(org_id)
    return Envelope(
        data=[OrgMemberOut(user_id=u.id, email=u.email, name=u.name, service_account=u.service_account, status="member") for u in members]
    )


@router.put("/users/{user_id}", tags=["Org Users"], dependencies=[require(Scope.users_write)])
async def add_org_user(user_id: UUID, org_id: OrgDep) -> Envelope[MembershipOut]:
    """Idempotent: the org comes from the credential, so membership can only ever be granted in scope."""
    if await User.find_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if await OrgMembership.get((user_id, org_id)) is None:
        await OrgMembership(user_id=user_id, org_id=org_id).save()
    return Envelope(data=MembershipOut(user_id=user_id, org_id=org_id, status="member"))


@router.delete("/users/{user_id}", tags=["Org Users"], dependencies=[require(Scope.users_write)])
async def remove_org_user(user_id: UUID, org_id: OrgDep) -> Envelope[DeletedOut[str]]:
    """Removing the membership cascades the user out of the org's workspaces."""
    membership = await OrgMembership.get((user_id, org_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="User is not a member of this org")
    await membership.delete()
    return Envelope(data=DeletedOut.of(f"{user_id}/{org_id}"))


@router.get("/management-keys", tags=["Management Keys"], dependencies=[require(Scope.management_keys_read)])
async def list_management_keys(org_id: OrgDep) -> Envelope[list[ManagementKeyOut]]:
    keys = await ManagementKey.find(ManagementKey.org_id == org_id, order_by=col(ManagementKey.id))
    return Envelope(data=[ManagementKeyOut.model_validate(k) for k in keys])


@router.post("/management-keys", tags=["Management Keys"], dependencies=[require(Scope.management_keys_write)])
async def mint_org_management_key(body: ManagementKeyIn, org_id: OrgDep, claims: MgmtDep) -> Envelope[ManagementKeyMintedOut]:
    """Mint an org-scoped key for the acting user, or for another org member when user_id names one."""
    user_id = body.user_id or claims.user_id
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.instance_admin and await OrgMembership.get((user_id, org_id)) is None:
        raise HTTPException(status_code=403, detail="User is not a member of this org, so a key cannot be minted for them")
    scopes = [s.value for s in body.scopes] if body.scopes is not None else None
    key_id, token = await mint_management_key(org_id, user_id, label=body.label, scopes=scopes)
    return Envelope(data=ManagementKeyMintedOut(id=key_id, org_id=org_id, user_id=user_id, scopes=scopes, label=body.label, token=token))


@router.delete("/management-keys/{key_id}", tags=["Management Keys"], dependencies=[require(Scope.management_keys_write)])
async def revoke_management_key(org_id: OrgDep, key_id: UUID) -> Envelope[ManagementKeyRevokedOut]:
    key = await ManagementKey.owned_by(org_id, key_id)
    key.revoked = True
    await key.save()
    return Envelope(data=ManagementKeyRevokedOut(id=key_id, status="revoked"))


@router.post("/bundles/compile", tags=["Bundles"], dependencies=[require(Scope.bundles_write)])
async def compile_bundle(org_id: OrgDep, request: Request) -> Envelope[BundleOut]:
    settings = request.app.state.settings
    now = datetime.now(tz=UTC)
    try:
        bundle = await compile_and_store(org_id, uuid7(), now, settings.bundle.staleness_bound, settings.bundle.signing_key)
    except UnknownOrgError as e:
        raise HTTPException(status_code=404, detail="Organization not found") from e
    return Envelope(data=BundleOut.model_validate(bundle))


@router.get("/bundles", tags=["Bundles"], dependencies=[require(Scope.bundles_read)])
async def list_bundles(org_id: OrgDep) -> Envelope[list[BundleOut]]:
    bundles = await Bundle.find(Bundle.org_id == org_id, order_by=col(Bundle.version))
    return Envelope(data=[BundleOut.model_validate(b) for b in bundles])


@router.get("/events", tags=["Events"], dependencies=[require(Scope.events_read)])
async def list_events(org_id: OrgDep, after: datetime | None = None, limit: int = 50) -> Envelope[list[UsageEventOut]]:
    occurred_at = col(UsageEvent.occurred_at)
    # Paging forward from a cursor reads oldest first; the unanchored view is the newest events.
    after_cursor = (occurred_at > after,) if after is not None else ()
    order = occurred_at.asc() if after is not None else occurred_at.desc()
    events = await UsageEvent.find(UsageEvent.org_id == org_id, *after_cursor, order_by=order, limit=limit)
    return Envelope(data=[UsageEventOut.model_validate(e) for e in events])


@router.get("/activity", tags=["Activity"], dependencies=[require(Scope.activity_read)])
async def list_activity(org_id: OrgDep, limit: int = 50) -> Envelope[list[ActivityOut]]:
    """What changed in this org, newest first: the audit trail the write triggers already record."""
    return Envelope(data=[ActivityOut.model_validate(entry) for entry in await AuditLog.for_org(org_id, limit)])
