from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import col

from control_plane.deps import instance_scope
from control_plane.models import MgmtToken, Org, OrgMembership, User
from control_plane.models.mgmt_token import MgmtTokenOut, MintedTokenOut, TokenRevokedOut, UserTokenIn
from control_plane.models.org import OrgCreate, OrgOut, OrgPatch
from control_plane.models.org_membership import MembershipOut
from control_plane.models.user import ServiceAccountIn, UserCreate, UserOut
from control_plane.schemas import DeletedOut, Envelope
from control_plane.tokens import mint_mgmt

router = APIRouter(prefix="/instance", dependencies=[Depends(instance_scope)])


async def _mint(request: Request, org_id: str | None, user_id: str | None = None) -> MintedTokenOut:
    settings = request.app.state.settings
    token_id, token = await mint_mgmt(org_id, settings.auth.token_signing_key, datetime.now(tz=UTC), user_id)
    return MintedTokenOut(token_id=token_id, org_id=org_id, user_id=user_id, token=token)


@router.post("/orgs")
async def create_org(body: OrgCreate) -> Envelope[OrgOut]:
    if await Org.get(body.id) is not None:
        raise HTTPException(status_code=409)
    org = await Org(id=body.id, name=body.name or body.id).save()
    return Envelope(data=OrgOut.model_validate(org))


@router.patch("/orgs/{org_id}")
async def update_org(org_id: str, body: OrgPatch) -> Envelope[OrgOut]:
    org = await Org.get(org_id)
    if org is None:
        raise HTTPException(status_code=404)
    for name, value in body.model_dump(exclude_unset=True).items():
        setattr(org, name, value)
    return Envelope(data=OrgOut.model_validate(await org.save()))


@router.get("/orgs")
async def list_orgs() -> Envelope[list[OrgOut]]:
    return Envelope(data=[OrgOut.model_validate(r) for r in await Org.find(order_by=col(Org.id))])


@router.post("/users")
async def create_user(body: UserCreate) -> Envelope[UserOut]:
    if await User.first(User.email == body.email) is not None:
        raise HTTPException(status_code=409)
    user = User(id=f"u-{uuid4().hex[:8]}", email=body.email, name=body.name or body.email, instance_admin=body.instance_admin, service_account=False)
    return Envelope(data=_user_out(await user.save(), []))


@router.post("/service-accounts")
async def create_service_account(body: ServiceAccountIn) -> Envelope[UserOut]:
    user = User.new_service_account(body.name, instance_admin=body.instance_admin)
    return Envelope(data=_user_out(await user.save(), []))


def _user_out(u: User, orgs: list[str]) -> UserOut:
    return UserOut.model_validate({**u.model_dump(), "orgs": orgs})


@router.get("/users")
async def list_users() -> Envelope[list[UserOut]]:
    users = await User.find(order_by=col(User.email))
    memberships = await OrgMembership.find(order_by=col(OrgMembership.org_id))
    orgs_by_user: dict[str, list[str]] = {}
    for m in memberships:
        orgs_by_user.setdefault(m.user_id, []).append(m.org_id)
    return Envelope(data=[_user_out(u, orgs_by_user.get(u.id, [])) for u in users])


@router.put("/users/{user_id}/orgs/{org_id}")
async def add_membership(user_id: str, org_id: str) -> Envelope[MembershipOut]:
    if await User.get(user_id) is None or await Org.get(org_id) is None:
        raise HTTPException(status_code=404)
    if await OrgMembership.get((user_id, org_id)) is None:
        await OrgMembership(user_id=user_id, org_id=org_id).save()
    return Envelope(data=MembershipOut(user_id=user_id, org_id=org_id, status="member"))


@router.delete("/users/{user_id}/orgs/{org_id}")
async def remove_membership(user_id: str, org_id: str) -> Envelope[DeletedOut[str]]:
    membership = await OrgMembership.get((user_id, org_id))
    if membership is None:
        raise HTTPException(status_code=404)
    await membership.delete()
    return Envelope(data=DeletedOut(id=f"{user_id}/{org_id}", deleted_at=datetime.now(tz=UTC)))


@router.post("/users/{user_id}/tokens")
async def mint_user_token(user_id: str, request: Request, body: UserTokenIn | None = None) -> Envelope[MintedTokenOut]:
    user = await User.get(user_id)
    if user is None:
        raise HTTPException(status_code=404)
    org_id = body.org_id if body else None
    if org_id is None:
        if not user.instance_admin:
            raise HTTPException(status_code=403)
    else:
        if await Org.get(org_id) is None:
            raise HTTPException(status_code=404)
        if not user.instance_admin and await OrgMembership.get((user_id, org_id)) is None:
            raise HTTPException(status_code=403)
    return Envelope(data=await _mint(request, org_id, user_id))


@router.post("/tokens")
async def mint_instance_token(request: Request) -> Envelope[MintedTokenOut]:
    return Envelope(data=await _mint(request, None))


@router.post("/orgs/{org_id}/tokens")
async def mint_org_token(org_id: str, request: Request) -> Envelope[MintedTokenOut]:
    if await Org.get(org_id) is None:
        raise HTTPException(status_code=404)
    return Envelope(data=await _mint(request, org_id))


@router.get("/tokens")
async def list_tokens(org_id: str | None = None) -> Envelope[list[MgmtTokenOut]]:
    conditions = (MgmtToken.org_id == org_id,) if org_id else ()
    return Envelope(data=[MgmtTokenOut.model_validate(r) for r in await MgmtToken.find(*conditions, order_by=col(MgmtToken.id))])


@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: str) -> Envelope[TokenRevokedOut]:
    """Revoke any management token by id; unknown ids get a tombstone so offline-minted tokens can be killed too."""
    row = await MgmtToken.get(token_id)
    if row is None:
        row = MgmtToken(id=token_id, org_id=None, revoked=True)
    else:
        row.revoked = True
    await row.save()
    return Envelope(data=TokenRevokedOut(token_id=token_id, status="revoked"))
