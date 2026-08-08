from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from control_plane.deps import ActingUserDep, FetchSite, RequestedWith, SessionCookie, SessionDep, public, require_csrf, user_scoped
from control_plane.models import AuthIdentity, OrgMembership, User, set_actor
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.passwords import DUMMY_HASH, hash_password, needs_rehash, verify_password
from control_plane.sessions import SESSION_ABSOLUTE_TTL, SESSION_COOKIE, mint_session, verify_session

if TYPE_CHECKING:
    from control_plane.config import Settings

router = APIRouter(prefix="/auth")


class LoginIn(BaseModel):
    email: str
    password: str


class SignupIn(BaseModel):
    email: str
    name: str = ""
    password: str = Field(min_length=8)


class MeOut(BaseModel):
    user_id: UUID
    email: str
    name: str
    instance_admin: bool
    orgs: list[UUID]


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class PasswordChangedOut(BaseModel):
    user_id: UUID
    status: Literal["changed"]


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=not settings.dev,
        path="/",
        max_age=int(SESSION_ABSOLUTE_TTL.total_seconds()),
    )


async def _me_out(user: User) -> MeOut:
    memberships = await OrgMembership.find(OrgMembership.user_id == user.id)
    return MeOut(user_id=user.id, email=user.email, name=user.name, instance_admin=user.instance_admin, orgs=sorted(m.org_id for m in memberships))


async def _login_user(email: str, password: str) -> User:
    """Password verification with one 401 for every failure shape, so responses never say which part was wrong."""
    identity = await AuthIdentity.password_for(email)
    if identity is None or identity.secret_hash is None:
        verify_password(DUMMY_HASH, password)
        raise HTTPException(status_code=401)
    if not verify_password(identity.secret_hash, password):
        raise HTTPException(status_code=401)
    user = await User.find_by_id(identity.user_id)
    if user is None or user.service_account:
        raise HTTPException(status_code=401)
    if needs_rehash(identity.secret_hash):
        identity.secret_hash = hash_password(password)
        await identity.save()
    return user


@router.post("/login", tags=["Auth"], dependencies=[public()])
async def login(body: LoginIn, request: Request, response: Response, _session: SessionDep) -> Envelope[MeOut]:
    user = await _login_user(body.email, body.password)
    _, token = await mint_session(user.id)
    _set_session_cookie(response, token, request.app.state.settings)
    return Envelope(data=await _me_out(user))


@router.post("/signup", tags=["Auth"], dependencies=[public()])
async def signup(body: SignupIn, request: Request, response: Response, _session: SessionDep) -> Envelope[MeOut]:
    """Open self-signup: a fresh account holds no memberships and no admin bit, so it can see nothing until granted."""
    if await User.first(User.email == body.email) is not None:
        raise HTTPException(status_code=409)
    user = User(email=body.email, name=body.name or body.email, instance_admin=False, service_account=False)
    await set_actor(user.id)
    await user.save()
    await AuthIdentity.set_password(user, body.password)
    _, token = await mint_session(user.id)
    _set_session_cookie(response, token, request.app.state.settings)
    return Envelope(data=await _me_out(user))


@router.post("/logout", tags=["Auth"], dependencies=[user_scoped()])
async def logout(
    response: Response,
    _session: SessionDep,
    session_cookie: SessionCookie = None,
    x_requested_with: RequestedWith = None,
    sec_fetch_site: FetchSite = None,
) -> Envelope[DeletedOut[UUID]]:
    if session_cookie is None:
        raise HTTPException(status_code=401)
    require_csrf(x_requested_with, sec_fetch_site)
    auth_session = await verify_session(session_cookie)
    if auth_session is None:
        raise HTTPException(status_code=401)
    await auth_session.delete()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return Envelope(data=DeletedOut(id=auth_session.id, deleted_at=datetime.now(tz=UTC)))


@router.get("/me", tags=["Auth"], dependencies=[user_scoped()])
async def me(user: ActingUserDep) -> Envelope[MeOut]:
    return Envelope(data=await _me_out(user))


@router.post("/password", tags=["Auth"], dependencies=[user_scoped()])
async def change_password(body: PasswordChangeIn, user: ActingUserDep) -> Envelope[PasswordChangedOut]:
    identity = await AuthIdentity.password_for(user.email)
    if identity is None or identity.secret_hash is None or not verify_password(identity.secret_hash, body.current_password):
        raise HTTPException(status_code=403)
    await AuthIdentity.set_password(user, body.new_password)
    return Envelope(data=PasswordChangedOut(user_id=user.id, status="changed"))
