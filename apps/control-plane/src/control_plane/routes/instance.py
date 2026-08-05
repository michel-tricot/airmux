from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlmodel import col

from contract import private_key_from_b64
from control_plane.deps import instance_scope
from control_plane.models import MgmtToken, Org, OrgMembership, User
from control_plane.tokens import mint_management_token

router = APIRouter(prefix="/instance", dependencies=[Depends(instance_scope)])


class OrgIn(BaseModel):
    id: str = Field(description="Org id, e.g. org-dev")
    name: str = Field("", description="Display name, defaults to the id")


class OrgOut(BaseModel):
    id: str


class MgmtTokenOut(BaseModel):
    token_id: str
    org_id: str | None
    user_id: str | None = None
    token: str


class TokenRevokedOut(BaseModel):
    token_id: str
    status: Literal["revoked"]


SERVICE_ACCOUNT_EMAIL_DOMAIN = "airbytesvcaccount.ai"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class UserIn(BaseModel):
    email: str = Field(description="Unique email identifying the user")
    name: str = Field("", description="Display name, defaults to the email")
    instance_admin: bool = Field(default=False, description="Whether the user administers the whole instance")


class ServiceAccountIn(BaseModel):
    name: str = Field(description="Service account name; the email is derived as name-<id>@airbytesvcaccount.ai")
    instance_admin: bool = Field(default=False, description="Whether the service account administers the whole instance")

    @field_validator("name")
    @classmethod
    def name_yields_an_email_local_part(cls, v: str) -> str:
        if not _slug(v):
            msg = "name must contain at least one letter or digit"
            raise ValueError(msg)
        return v


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    instance_admin: bool
    service_account: bool
    created_at: datetime
    orgs: list[str]


class UserTokenIn(BaseModel):
    org_id: str | None = Field(None, description="Org to scope the token to; omit for an instance token, instance admins only")


class MembershipOut(BaseModel):
    user_id: str
    org_id: str
    status: Literal["member", "removed"]


async def _mint(request: Request, org_id: str | None, user_id: str | None = None) -> MgmtTokenOut:
    now = datetime.now(tz=UTC)
    token_id = f"mt-{uuid4().hex[:8]}"
    await MgmtToken(id=token_id, org_id=org_id, user_id=user_id, revoked=False).save()
    settings = request.app.state.settings
    token = mint_management_token(org_id, private_key_from_b64(settings.auth.token_signing_key), now, token_id, user_id)
    return MgmtTokenOut(token_id=token_id, org_id=org_id, user_id=user_id, token=token)


@router.post("/orgs")
async def create_org(body: OrgIn) -> OrgOut:
    if await Org.get(body.id) is not None:
        raise HTTPException(status_code=409)
    await Org(id=body.id, name=body.name or body.id).save()
    return OrgOut(id=body.id)


@router.get("/orgs")
async def list_orgs() -> list[Org]:
    return await Org.find(order_by=col(Org.id))


@router.post("/users")
async def create_user(body: UserIn) -> UserOut:
    if await User.first(User.email == body.email) is not None:
        raise HTTPException(status_code=409)
    user = User(id=f"u-{uuid4().hex[:8]}", email=body.email, name=body.name or body.email, instance_admin=body.instance_admin, service_account=False)
    return _user_out(await user.save(), [])


@router.post("/service-accounts")
async def create_service_account(body: ServiceAccountIn) -> UserOut:
    user = User(
        id=f"u-{uuid4().hex[:8]}",
        email=f"{_slug(body.name)}-{uuid4().hex[:8]}@{SERVICE_ACCOUNT_EMAIL_DOMAIN}",
        name=body.name,
        instance_admin=body.instance_admin,
        service_account=True,
    )
    return _user_out(await user.save(), [])


def _user_out(u: User, orgs: list[str]) -> UserOut:
    return UserOut(
        id=u.id, email=u.email, name=u.name, instance_admin=u.instance_admin, service_account=u.service_account, created_at=u.created_at, orgs=orgs
    )


@router.get("/users")
async def list_users() -> list[UserOut]:
    users = await User.find(order_by=col(User.email))
    memberships = await OrgMembership.find(order_by=col(OrgMembership.org_id))
    orgs_by_user: dict[str, list[str]] = {}
    for m in memberships:
        orgs_by_user.setdefault(m.user_id, []).append(m.org_id)
    return [_user_out(u, orgs_by_user.get(u.id, [])) for u in users]


@router.put("/users/{user_id}/orgs/{org_id}")
async def add_membership(user_id: str, org_id: str) -> MembershipOut:
    if await User.get(user_id) is None or await Org.get(org_id) is None:
        raise HTTPException(status_code=404)
    if await OrgMembership.get((user_id, org_id)) is None:
        await OrgMembership(user_id=user_id, org_id=org_id).save()
    return MembershipOut(user_id=user_id, org_id=org_id, status="member")


@router.delete("/users/{user_id}/orgs/{org_id}")
async def remove_membership(user_id: str, org_id: str) -> MembershipOut:
    membership = await OrgMembership.get((user_id, org_id))
    if membership is None:
        raise HTTPException(status_code=404)
    await membership.delete()
    return MembershipOut(user_id=user_id, org_id=org_id, status="removed")


@router.post("/users/{user_id}/tokens")
async def mint_user_token(user_id: str, request: Request, body: UserTokenIn | None = None) -> MgmtTokenOut:
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
    return await _mint(request, org_id, user_id)


@router.post("/tokens")
async def mint_instance_token(request: Request) -> MgmtTokenOut:
    return await _mint(request, None)


@router.post("/orgs/{org_id}/tokens")
async def mint_org_token(org_id: str, request: Request) -> MgmtTokenOut:
    if await Org.get(org_id) is None:
        raise HTTPException(status_code=404)
    return await _mint(request, org_id)


@router.get("/tokens")
async def list_tokens(org_id: str | None = None) -> list[MgmtToken]:
    conditions = (MgmtToken.org_id == org_id,) if org_id else ()
    return await MgmtToken.find(*conditions, order_by=col(MgmtToken.id))


@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: str) -> TokenRevokedOut:
    """Revoke any management token by id; unknown ids get a tombstone so offline-minted tokens can be killed too."""
    row = await MgmtToken.get(token_id)
    if row is None:
        row = MgmtToken(id=token_id, org_id=None, revoked=True)
    else:
        row.revoked = True
    await row.save()
    return TokenRevokedOut(token_id=token_id, status="revoked")
