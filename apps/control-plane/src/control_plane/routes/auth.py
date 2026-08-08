from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from control_plane.deps import ActingUserDep, CookieUserDep, FetchSite, RequestedWith, SessionCookie, SessionDep, public, require_csrf, user_scoped
from control_plane.keys import mint_management_key
from control_plane.models import AuthIdentity, CliAuthRequest, ManagementKey, Org, OrgMembership, User, set_actor
from control_plane.models.cli_auth_request import AUTH_REQUEST_TTL
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.passwords import DUMMY_HASH, hash_password, needs_rehash, verify_password
from control_plane.sessions import SESSION_ABSOLUTE_TTL, SESSION_COOKIE, mint_session, verify_session

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


def _set_session_cookie(response: Response, token: str, request: Request) -> None:
    """Secure follows the request scheme: set over https, omitted over http so localhost and the
    docker network work without a dev flag. Deploy the control plane behind TLS in production."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
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
    _set_session_cookie(response, token, request)
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
    _set_session_cookie(response, token, request)
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


CLI_POLL_INTERVAL_SECONDS = 5


class CliAuthStartIn(BaseModel):
    client_name: str = Field(min_length=1, max_length=80, description="Where the CLI runs, e.g. the hostname; becomes the minted key's label")


class CliAuthStartOut(BaseModel):
    user_code: str
    verification_url: str
    poll_secret: str
    interval_seconds: int
    expires_in_seconds: int


class CliAuthRequestOut(BaseModel):
    client_name: str
    requester: str
    expires_at: datetime


class CliAuthApproveIn(BaseModel):
    user_code: str
    org_id: UUID


class CliAuthApprovedOut(BaseModel):
    status: Literal["approved"]
    client_name: str


class CliAuthPollIn(BaseModel):
    poll_secret: str


class CliAuthPollOut(BaseModel):
    status: Literal["pending", "complete"]
    interval_seconds: int
    token: str | None = None
    org_id: UUID | None = None
    org_name: str | None = None


def _live(auth_request: CliAuthRequest | None) -> CliAuthRequest:
    if auth_request is None:
        raise HTTPException(status_code=404)
    if auth_request.expired:
        raise HTTPException(status_code=410)
    return auth_request


@router.post("/cli/start", tags=["Auth"], dependencies=[public()])
async def cli_auth_start(body: CliAuthStartIn, request: Request, _session: SessionDep) -> Envelope[CliAuthStartOut]:
    """Open a device authorization: unauthenticated like signup, it grants nothing by itself."""
    _, user_code, poll_secret = await CliAuthRequest.open(body.client_name, request.client.host if request.client else "")
    settings = request.app.state.settings
    return Envelope(
        data=CliAuthStartOut(
            user_code=user_code,
            verification_url=f"{settings.webapp_url.rstrip('/')}/cli?code={quote(user_code)}",
            poll_secret=poll_secret,
            interval_seconds=CLI_POLL_INTERVAL_SECONDS,
            expires_in_seconds=int(AUTH_REQUEST_TTL.total_seconds()),
        )
    )


@router.get("/cli/request", tags=["Auth"], dependencies=[user_scoped()])
async def cli_auth_request_details(code: str, _user: CookieUserDep) -> Envelope[CliAuthRequestOut]:
    """Context for the approve page: who is asking, from where, until when."""
    auth_request = _live(await CliAuthRequest.by_user_code(code))
    if auth_request.approved_user_id is not None:
        raise HTTPException(status_code=409)
    return Envelope(
        data=CliAuthRequestOut(client_name=auth_request.client_name, requester=auth_request.requester, expires_at=auth_request.expires_at)
    )


@router.post("/cli/approve", tags=["Auth"], dependencies=[user_scoped()])
async def cli_auth_approve(body: CliAuthApproveIn, user: CookieUserDep) -> Envelope[CliAuthApprovedOut]:
    """The human confirms the code and picks the org; membership backs the pick like key minting."""
    auth_request = _live(await CliAuthRequest.by_user_code(body.user_code))
    if auth_request.approved_user_id is not None:
        raise HTTPException(status_code=409)
    if await Org.find_by_id(body.org_id) is None:
        raise HTTPException(status_code=403)
    if not user.instance_admin and await OrgMembership.get((user.id, body.org_id)) is None:
        raise HTTPException(status_code=403)
    auth_request.approved_user_id = user.id
    auth_request.approved_org_id = body.org_id
    await auth_request.save()
    return Envelope(data=CliAuthApprovedOut(status="approved", client_name=auth_request.client_name))


@router.post("/cli/poll", tags=["Auth"], dependencies=[public()])
async def cli_auth_poll(body: CliAuthPollIn, _session: SessionDep) -> Envelope[CliAuthPollOut]:
    """The CLI's side of the flow: pending until approved, then the key exactly once.

    The key is minted here, not at approve, so its plaintext never rests in the pending request;
    deleting the request in the same transaction makes delivery one-time. Route-level actor stamp
    like signup: the poller is anonymous, the audited key write is attributed to the human who
    approved. Re-approving from the same client replaces that client's previous key for the org
    instead of accumulating.
    """
    auth_request = _live(await CliAuthRequest.by_poll_secret(body.poll_secret))
    if auth_request.approved_user_id is None or auth_request.approved_org_id is None:
        return Envelope(data=CliAuthPollOut(status="pending", interval_seconds=CLI_POLL_INTERVAL_SECONDS))
    org = await Org.find_by_id(auth_request.approved_org_id)
    if org is None:
        raise HTTPException(status_code=410)
    await set_actor(auth_request.approved_user_id)
    await ManagementKey.retire_for_client(auth_request.approved_user_id, auth_request.approved_org_id, auth_request.client_name)
    _, token = await mint_management_key(auth_request.approved_org_id, auth_request.approved_user_id, label=auth_request.client_name)
    await auth_request.delete()
    return Envelope(data=CliAuthPollOut(status="complete", interval_seconds=CLI_POLL_INTERVAL_SECONDS, token=token, org_id=org.id, org_name=org.name))
