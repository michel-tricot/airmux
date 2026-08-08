from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col

from control_plane.authz import Scope
from control_plane.deps import instance_scope, require
from control_plane.keys import mint_management_key
from control_plane.models import ManagementKey, Org, OrgMembership, User
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.management_key import ManagementKeyIn, ManagementKeyMintedOut, ManagementKeyOut, ManagementKeyRevokedOut
from control_plane.models.org_membership import MembershipOut
from control_plane.models.user import ServiceAccountIn, UserCreate, UserOut

router = APIRouter(prefix="/instance", dependencies=[Depends(instance_scope)])


@router.post("/users", tags=["Users"], dependencies=[require(Scope.users_write)])
async def create_user(body: UserCreate) -> Envelope[UserOut]:
    if await User.first(User.email == body.email) is not None:
        raise HTTPException(status_code=409)
    user = User(email=body.email, name=body.name or body.email, instance_admin=body.instance_admin, service_account=False)
    return Envelope(data=_user_out(await user.save(), []))


@router.post("/service-accounts", tags=["Users"], dependencies=[require(Scope.users_write)])
async def create_service_account(body: ServiceAccountIn) -> Envelope[UserOut]:
    user = User.new_service_account(body.name, instance_admin=body.instance_admin)
    return Envelope(data=_user_out(await user.save(), []))


def _user_out(u: User, orgs: list[UUID]) -> UserOut:
    return UserOut.model_validate({**u.model_dump(), "orgs": orgs})


@router.get("/users", tags=["Users"], dependencies=[require(Scope.users_read)])
async def list_users() -> Envelope[list[UserOut]]:
    users = await User.find(order_by=col(User.email))
    memberships = await OrgMembership.find(order_by=col(OrgMembership.org_id))
    orgs_by_user: dict[UUID, list[UUID]] = {}
    for m in memberships:
        orgs_by_user.setdefault(m.user_id, []).append(m.org_id)
    return Envelope(data=[_user_out(u, orgs_by_user.get(u.id, [])) for u in users])


@router.put("/users/{user_id}/orgs/{org_id}", tags=["Users"], dependencies=[require(Scope.users_write)])
async def add_membership(user_id: UUID, org_id: UUID) -> Envelope[MembershipOut]:
    if await User.find_by_id(user_id) is None or await Org.find_by_id(org_id) is None:
        raise HTTPException(status_code=404)
    if await OrgMembership.get((user_id, org_id)) is None:
        await OrgMembership(user_id=user_id, org_id=org_id).save()
    return Envelope(data=MembershipOut(user_id=user_id, org_id=org_id, status="member"))


@router.delete("/users/{user_id}/orgs/{org_id}", tags=["Users"], dependencies=[require(Scope.users_write)])
async def remove_membership(user_id: UUID, org_id: UUID) -> Envelope[DeletedOut[str]]:
    membership = await OrgMembership.get((user_id, org_id))
    if membership is None:
        raise HTTPException(status_code=404)
    await membership.delete()
    return Envelope(data=DeletedOut(id=f"{user_id}/{org_id}", deleted_at=datetime.now(tz=UTC)))


@router.post("/users/{user_id}/tokens", tags=["Management Tokens"], dependencies=[require(Scope.tokens_write)])
async def mint_user_token(user_id: UUID, body: ManagementKeyIn | None = None) -> Envelope[ManagementKeyMintedOut]:
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404)
    org_id = body.org_id if body else None
    if org_id is None:
        if not user.instance_admin:
            raise HTTPException(status_code=403)
    else:
        if await Org.find_by_id(org_id) is None:
            raise HTTPException(status_code=404)
        if not user.instance_admin and await OrgMembership.get((user_id, org_id)) is None:
            raise HTTPException(status_code=403)
    scopes = [s.value for s in body.scopes] if body and body.scopes is not None else None
    token_id, token = await mint_management_key(org_id, user_id, scopes=scopes)
    return Envelope(data=ManagementKeyMintedOut(id=token_id, org_id=org_id, user_id=user_id, scopes=scopes, token=token))


@router.get("/tokens", tags=["Management Tokens"], dependencies=[require(Scope.tokens_read)])
async def list_tokens(org_id: str | None = None) -> Envelope[list[ManagementKeyOut]]:
    conditions = (ManagementKey.org_id == org_id,) if org_id else ()
    return Envelope(data=[ManagementKeyOut.model_validate(r) for r in await ManagementKey.find(*conditions, order_by=col(ManagementKey.id))])


@router.delete("/tokens/{token_id}", tags=["Management Tokens"], dependencies=[require(Scope.tokens_write)])
async def revoke_token(token_id: UUID) -> Envelope[ManagementKeyRevokedOut]:
    key = await ManagementKey.find_by_id(token_id)
    if key is None:
        raise HTTPException(status_code=404)
    key.revoked = True
    await key.save()
    return Envelope(data=ManagementKeyRevokedOut(id=token_id, status="revoked"))
