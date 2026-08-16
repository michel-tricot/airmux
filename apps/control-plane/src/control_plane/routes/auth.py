from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from control_plane.authz import Authority, Boundary, InstanceRole, Target, principal_permissions
from control_plane.deps import (
    ActingUserDep,
    AuthorityDep,
    BearerDep,
    CookieUserDep,
    FetchSite,
    RequestedWith,
    SessionCookie,
    browser_scoped,
    public,
    require_csrf,
    user_scoped,
)
from control_plane.keys import AccessKeyGrant, mint_access_key, verify_access_key
from control_plane.models import AccessKey, AuthIdentity, CliAuthRequest, Org, OrgMembership, User, set_actor
from control_plane.models.auth_identity import IdentityConflictError
from control_plane.models.cli_auth_request import AUTH_REQUEST_TTL
from control_plane.models.common.wire import DeletedOut, Envelope, RequestModel
from control_plane.passwords import DUMMY_HASH, hash_password, needs_rehash, verify_password
from control_plane.sessions import SESSION_ABSOLUTE_TTL, SESSION_COOKIE, mint_session, verify_session

router = APIRouter(prefix="/auth")


class LoginIn(RequestModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, email: str) -> str:
        return User.normalize_email(email)


class SignupIn(RequestModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field("", max_length=200)
    password: str = Field(min_length=8, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, email: str) -> str:
        return User.normalize_email(email)


class MeOut(BaseModel):
    user_id: UUID
    email: str
    name: str
    instance_role: InstanceRole | None
    orgs: list[UUID]


class PasswordChangeIn(RequestModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=8, max_length=1024)


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


async def _me_out(user: User, authority: Authority | None = None) -> MeOut:
    memberships = await OrgMembership.find(OrgMembership.user_id == user.id)
    orgs = sorted(membership.org_id for membership in memberships)
    if authority is not None and authority.boundary in {Boundary.org, Boundary.workspace}:
        orgs = [org_id for org_id in orgs if org_id == authority.org_id]
    return MeOut(user_id=user.id, email=user.email, name=user.name, instance_role=user.instance_role, orgs=orgs)


async def _login_user(email: str, password: str) -> User:
    """Password verification with one 401 for every failure shape, so responses never say which part was wrong."""
    identity = await AuthIdentity.password_for(email)
    if identity is None or identity.secret_hash is None:
        verify_password(DUMMY_HASH, password)
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not verify_password(identity.secret_hash, password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    user = await User.find_by_id(identity.user_id)
    if user is None or user.service_account:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if needs_rehash(identity.secret_hash):
        identity.secret_hash = hash_password(password)
        await identity.save()
    return user


@router.post("/login", tags=["Auth"], dependencies=[public()])
async def login(body: LoginIn, request: Request, response: Response) -> Envelope[MeOut]:
    user = await _login_user(body.email, body.password)
    _, token = await mint_session(user.id)
    _set_session_cookie(response, token, request)
    return Envelope(data=await _me_out(user))


@router.post("/signup", tags=["Auth"], dependencies=[public()])
async def signup(body: SignupIn, request: Request, response: Response) -> Envelope[MeOut]:
    """Open self-signup: an account holds no memberships, so it can see nothing until granted or until it founds an org.

    The exception is the first human on a deployment, who claims it and becomes its instance owner: a
    fresh install has no other way to reach the instance endpoints, and /instance/oss/claim exists to
    route that first visitor here. Every signup after the claim is an ordinary account. Anyone who can
    reach an unclaimed deployment can therefore take it, which is the same trapdoor the quickstart
    endpoint opens; complete the first signup before exposing the deployment.
    """
    if await User.first(User.email == body.email) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    instance_role = InstanceRole.owner if await User.claims_the_instance() else None
    user = User(email=body.email, name=body.name or body.email, instance_role=instance_role, service_account=False)
    await set_actor(user.id)
    await user.save()
    try:
        await AuthIdentity.set_password(user, body.password)
    except IdentityConflictError as e:
        raise HTTPException(status_code=409, detail="An account with this email already exists") from e
    _, token = await mint_session(user.id)
    _set_session_cookie(response, token, request)
    return Envelope(data=await _me_out(user))


@router.post("/logout", tags=["Auth"], dependencies=[browser_scoped()])
async def logout(
    response: Response,
    session_cookie: SessionCookie = None,
    x_requested_with: RequestedWith = None,
    sec_fetch_site: FetchSite = None,
) -> Envelope[DeletedOut[UUID]]:
    if session_cookie is None:
        raise HTTPException(status_code=401, detail="You are not signed in")
    require_csrf(x_requested_with, sec_fetch_site)
    auth_session = await verify_session(session_cookie)
    if auth_session is None:
        raise HTTPException(status_code=401, detail="Your session has expired; sign in again")
    await auth_session.delete()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return Envelope(data=DeletedOut.of(auth_session.id))


@router.get("/me", tags=["Auth"], dependencies=[user_scoped()])
async def me(user: ActingUserDep, authority: AuthorityDep) -> Envelope[MeOut]:
    return Envelope(data=await _me_out(user, authority))


@router.post("/password", tags=["Auth"], dependencies=[user_scoped()])
async def change_password(body: PasswordChangeIn, user: ActingUserDep) -> Envelope[PasswordChangedOut]:
    identity = await AuthIdentity.password_for(user.email)
    if identity is None or identity.secret_hash is None or not verify_password(identity.secret_hash, body.current_password):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    await AuthIdentity.set_password(user, body.new_password)
    return Envelope(data=PasswordChangedOut(user_id=user.id, status="changed"))


CLI_POLL_INTERVAL_SECONDS = 5


class CliAuthStartIn(RequestModel):
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


class CliAuthApproveIn(RequestModel):
    user_code: str = Field(min_length=8, max_length=16)
    org_id: UUID


class CliAuthApprovedOut(BaseModel):
    status: Literal["approved"]
    client_name: str


class CliAuthPollIn(RequestModel):
    poll_secret: str = Field(min_length=1, max_length=256)


class CliAuthPollOut(BaseModel):
    status: Literal["pending", "complete"]
    interval_seconds: int
    token: str | None = None
    org_id: UUID | None = None
    org_name: str | None = None


def _live(auth_request: CliAuthRequest | None) -> CliAuthRequest:
    if auth_request is None:
        raise HTTPException(status_code=404, detail="No sign-in request matches this code; check it and try again")
    if auth_request.expired:
        raise HTTPException(status_code=410, detail="This sign-in request has expired; start again from the CLI")
    return auth_request


@router.post("/cli/start", tags=["Auth"], dependencies=[public()])
async def cli_auth_start(body: CliAuthStartIn, request: Request) -> Envelope[CliAuthStartOut]:
    """Open a device authorization: unauthenticated like signup, it grants nothing by itself."""
    _, user_code, poll_secret = await CliAuthRequest.open(body.client_name, request.client.host if request.client else "")
    settings = request.app.state.settings
    return Envelope(
        data=CliAuthStartOut(
            user_code=user_code,
            verification_url=f"{settings.console_url.rstrip('/')}/cli?code={quote(user_code)}",
            poll_secret=poll_secret,
            interval_seconds=CLI_POLL_INTERVAL_SECONDS,
            expires_in_seconds=int(AUTH_REQUEST_TTL.total_seconds()),
        )
    )


@router.get("/cli/request", tags=["Auth"], dependencies=[browser_scoped()])
async def cli_auth_request_details(code: str, _user: CookieUserDep) -> Envelope[CliAuthRequestOut]:
    """Context for the approve page: who is asking, from where, until when."""
    auth_request = _live(await CliAuthRequest.by_user_code(code))
    if auth_request.approved_user_id is not None:
        raise HTTPException(status_code=409, detail="This sign-in request was already approved")
    return Envelope(
        data=CliAuthRequestOut(client_name=auth_request.client_name, requester=auth_request.requester, expires_at=auth_request.expires_at)
    )


@router.post("/cli/approve", tags=["Auth"], dependencies=[browser_scoped()])
async def cli_auth_approve(body: CliAuthApproveIn, user: CookieUserDep) -> Envelope[CliAuthApprovedOut]:
    """The human confirms the code and picks the org; membership backs the pick like key minting."""
    auth_request = _live(await CliAuthRequest.for_approval(body.user_code))
    if auth_request.approved_user_id is not None:
        raise HTTPException(status_code=409, detail="This sign-in request was already approved")
    if await Org.find_by_id(body.org_id) is None:
        raise HTTPException(status_code=403, detail="That organization no longer exists")
    if not await user.backs_org(body.org_id):
        raise HTTPException(status_code=403, detail="You are not a member of that organization")
    auth_request.approved_user_id = user.id
    auth_request.approved_org_id = body.org_id
    await auth_request.save()
    return Envelope(data=CliAuthApprovedOut(status="approved", client_name=auth_request.client_name))


@router.post("/cli/poll", tags=["Auth"], dependencies=[public()])
async def cli_auth_poll(body: CliAuthPollIn, credentials: BearerDep) -> Envelope[CliAuthPollOut]:
    """Return pending state or consume an approved request and deliver its key once.

    A valid existing bearer retires exactly that key when its principal and target match the
    approval. An absent, stale, or unrelated bearer changes nothing.
    """
    auth_request = _live(await CliAuthRequest.for_delivery(body.poll_secret))
    if auth_request.approved_user_id is None or auth_request.approved_org_id is None:
        return Envelope(data=CliAuthPollOut(status="pending", interval_seconds=CLI_POLL_INTERVAL_SECONDS))
    org = await Org.find_by_id(auth_request.approved_org_id)
    if org is None:
        raise HTTPException(status_code=410, detail="The approved organization no longer exists; start again")
    await set_actor(auth_request.approved_user_id)
    target = Target.org(org.id)
    now = datetime.now(tz=UTC)
    replaced = await verify_access_key(credentials.credentials) if credentials is not None else None
    if replaced is not None:
        await AccessKey.retire_replaced(replaced.credential_id, auth_request.approved_user_id, target, now)
    permissions = await principal_permissions(auth_request.approved_user_id, target)
    _, token = await mint_access_key(
        AccessKeyGrant(
            principal_id=auth_request.approved_user_id,
            target=target,
            permissions=permissions,
            label=auth_request.client_name,
        )
    )
    await auth_request.delete()
    return Envelope(data=CliAuthPollOut(status="complete", interval_seconds=CLI_POLL_INTERVAL_SECONDS, token=token, org_id=org.id, org_name=org.name))
