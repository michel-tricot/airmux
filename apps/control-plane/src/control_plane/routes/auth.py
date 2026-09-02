from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, BeforeValidator, Field, RootModel, field_validator

from contract import PLAYGROUND_COOKIE
from control_plane.authority import effective_permissions, principal_can_issue_instance_access_key, principal_can_select_org, visible_org_ids
from control_plane.authz import Actor, InstanceRole, Permission, Scope
from control_plane.deps import (
    ActingUserDep,
    ActorDep,
    BearerDep,
    CookieUserDep,
    FetchSite,
    PermissionScopeDep,
    RequestedWith,
    SessionCookie,
    browser_scoped,
    principal_scoped,
    public,
    require_csrf,
    user_scoped,
)
from control_plane.keys import mint_standing_access_key, verify_access_key
from control_plane.models import AccessKey, AuthIdentity, CliAuthRequest, Org, OrgMembership, PlaygroundSession, User, set_actor
from control_plane.models.auth_identity import IdentityConflictError
from control_plane.models.cli_auth_request import AUTH_REQUEST_TTL
from control_plane.models.common.wire import DeletedOut, Envelope, RequestModel
from control_plane.passwords import DUMMY_HASH, hash_password, needs_rehash, verify_password
from control_plane.sessions import SESSION_ABSOLUTE_TTL, SESSION_COOKIE, mint_session, verify_session

router = APIRouter(prefix="/auth")


class LoginIn(RequestModel):
    email: str = Field(description="Account email address", min_length=3, max_length=320)
    password: str = Field(description="Account password", min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, email: str) -> str:
        return User.normalize_email(email)


class SignupIn(RequestModel):
    email: str = Field(description="Email address for the new account", min_length=3, max_length=320)
    name: str = Field("", description="Display name; defaults to the email address", max_length=200)
    password: str = Field(description="Password for the new account; at least 8 characters", min_length=8, max_length=1024)

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


class MyPermissionsOut(BaseModel):
    permissions: list[Permission] = Field(description="Permissions the credential can exercise at the requested scope")


class PasswordChangeIn(RequestModel):
    current_password: str = Field(description="Current account password", min_length=1, max_length=1024)
    new_password: str = Field(description="Replacement password; at least 8 characters", min_length=8, max_length=1024)


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


async def _me_out(user: User, actor: Actor | None = None) -> MeOut:
    memberships = await OrgMembership.find(OrgMembership.user_id == user.id)
    orgs = sorted(membership.org_id for membership in memberships)
    if actor is not None:
        orgs = visible_org_ids(actor, orgs)
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
    """Authenticate a human user and start a browser session."""
    user = await _login_user(body.email, body.password)
    _, token = await mint_session(user.id)
    _set_session_cookie(response, token, request)
    return Envelope(data=await _me_out(user))


@router.post("/signup", tags=["Auth"], dependencies=[public()])
async def signup(body: SignupIn, request: Request, response: Response) -> Envelope[MeOut]:
    """Create a human account and start a browser session.

    The first human account on a new deployment becomes the instance owner. Later accounts require
    an organization membership or instance role before they can access managed resources.
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
    _user: CookieUserDep,
    session_cookie: SessionCookie = None,
    x_requested_with: RequestedWith = None,
    sec_fetch_site: FetchSite = None,
) -> Envelope[DeletedOut[UUID]]:
    """End the current browser session and clear its cookie."""
    if session_cookie is None:
        raise HTTPException(status_code=401, detail="You are not signed in")
    require_csrf(x_requested_with, sec_fetch_site)
    auth_session = await verify_session(session_cookie)
    if auth_session is None:
        raise HTTPException(status_code=401, detail="Your session has expired; sign in again")
    playground_session = await PlaygroundSession.by_credential(auth_session.id)
    if playground_session is not None:
        playground_session.revoked = True
        await playground_session.save()
    await auth_session.delete()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(PLAYGROUND_COOKIE, path="/")
    return Envelope(data=DeletedOut.of(auth_session.id))


@router.get("/me", tags=["Auth"], dependencies=[user_scoped()])
async def me(user: ActingUserDep, actor: ActorDep) -> Envelope[MeOut]:
    """Return the authenticated human user and the organizations visible to this credential."""
    return Envelope(data=await _me_out(user, actor))


@router.get("/permissions", tags=["Auth"], dependencies=[principal_scoped()])
async def my_permissions(actor: ActorDep, scope: PermissionScopeDep) -> Envelope[MyPermissionsOut]:
    """Return the effective permissions this credential can exercise at the requested scope."""
    permissions = await effective_permissions(actor, scope)
    return Envelope(data=MyPermissionsOut(permissions=sorted(permissions)))


@router.post("/password", tags=["Auth"], dependencies=[user_scoped()])
async def change_password(body: PasswordChangeIn, user: ActingUserDep) -> Envelope[PasswordChangedOut]:
    """Replace the authenticated user's password after verifying the current password."""
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
    can_approve_instance: bool


class _CliAuthApproveIn(RequestModel):
    user_code: str = Field(description="Device code shown by the CLI", min_length=8, max_length=16)


class CliInstanceAuthApproveIn(_CliAuthApproveIn):
    scope: Literal["instance"] = Field("instance", description="Issue an instance-scoped CLI access key")
    org_id: None = Field(None, description="Organization is absent for instance access")


class CliOrgAuthApproveIn(_CliAuthApproveIn):
    scope: Literal["org"] = Field("org", description="Issue an organization-scoped CLI access key")
    org_id: UUID = Field(description="Organization the CLI access key should use")


def _default_cli_approval_scope(value: object) -> object:
    if isinstance(value, Mapping) and "scope" not in value:
        return {**value, "scope": "org"}
    return value


CliAuthApproval = Annotated[CliInstanceAuthApproveIn | CliOrgAuthApproveIn, Field(discriminator="scope")]
CliAuthApproveIn = Annotated[CliAuthApproval, BeforeValidator(_default_cli_approval_scope)]


class CliAuthApprovedOut(BaseModel):
    status: Literal["approved"]
    client_name: str


class CliAuthPollIn(RequestModel):
    poll_secret: str = Field(description="Polling secret returned when device authorization started", min_length=1, max_length=256)


class CliAuthPendingOut(BaseModel):
    status: Literal["pending"] = "pending"
    interval_seconds: int
    scope: None = None
    token: None = None
    org_id: None = None
    org_name: None = None


class CliAuthInstanceCompleteOut(BaseModel):
    status: Literal["complete"] = "complete"
    interval_seconds: int
    scope: Literal["instance"] = "instance"
    token: str
    org_id: None = None
    org_name: None = None


class CliAuthOrgCompleteOut(BaseModel):
    status: Literal["complete"] = "complete"
    interval_seconds: int
    scope: Literal["org"] = "org"
    token: str
    org_id: UUID
    org_name: str


class CliAuthPollOut(RootModel[CliAuthPendingOut | CliAuthInstanceCompleteOut | CliAuthOrgCompleteOut]):
    pass


def _live(auth_request: CliAuthRequest | None) -> CliAuthRequest:
    if auth_request is None:
        raise HTTPException(status_code=404, detail="No sign-in request matches this code; check it and try again")
    if auth_request.expired:
        raise HTTPException(status_code=410, detail="This sign-in request has expired; start again from the CLI")
    return auth_request


@router.post("/cli/start", tags=["Auth"], dependencies=[public()])
async def cli_auth_start(body: CliAuthStartIn, request: Request) -> Envelope[CliAuthStartOut]:
    """Create a short-lived device authorization for a CLI sign-in."""
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
async def cli_auth_request_details(code: str, user: CookieUserDep) -> Envelope[CliAuthRequestOut]:
    """Return the client and expiry details for a device authorization code."""
    auth_request = _live(await CliAuthRequest.by_user_code(code))
    if auth_request.approved_user_id is not None:
        raise HTTPException(status_code=409, detail="This sign-in request was already approved")
    return Envelope(
        data=CliAuthRequestOut(
            client_name=auth_request.client_name,
            requester=auth_request.requester,
            expires_at=auth_request.expires_at,
            can_approve_instance=await principal_can_issue_instance_access_key(user.id),
        )
    )


@router.post("/cli/approve", tags=["Auth"], dependencies=[browser_scoped()])
async def cli_auth_approve(body: CliAuthApproveIn, user: CookieUserDep) -> Envelope[CliAuthApprovedOut]:
    """Approve a device authorization for instance access or one visible organization."""
    auth_request = _live(await CliAuthRequest.for_approval(body.user_code))
    if auth_request.approved_user_id is not None:
        raise HTTPException(status_code=409, detail="This sign-in request was already approved")
    if body.scope == "instance":
        if not await principal_can_issue_instance_access_key(user.id):
            raise HTTPException(status_code=403, detail="You cannot approve instance CLI access")
    else:
        org_id = body.org_id
        if await Org.find_by_id(org_id) is None:
            raise HTTPException(status_code=403, detail="That organization no longer exists")
        if not await principal_can_select_org(user.id, org_id):
            raise HTTPException(status_code=403, detail="You are not a member of that organization")
    auth_request.approved_user_id = user.id
    auth_request.approved_org_id = body.org_id
    await auth_request.save()
    return Envelope(data=CliAuthApprovedOut(status="approved", client_name=auth_request.client_name))


@router.post("/cli/poll", tags=["Auth"], dependencies=[public()])
async def cli_auth_poll(body: CliAuthPollIn, credentials: BearerDep) -> Envelope[CliAuthPollOut]:
    """Return pending status or deliver the approved scoped access key once.

    When the request includes the CLI's current access key for the same user and scope, that
    key is revoked as part of replacement. Labels do not participate in matching.
    """
    auth_request = _live(await CliAuthRequest.for_delivery(body.poll_secret))
    if auth_request.approved_user_id is None:
        return Envelope(data=CliAuthPollOut(root=CliAuthPendingOut(interval_seconds=CLI_POLL_INTERVAL_SECONDS)))
    org = await Org.find_by_id(auth_request.approved_org_id) if auth_request.approved_org_id is not None else None
    if auth_request.approved_org_id is not None and org is None:
        raise HTTPException(status_code=410, detail="The approved organization no longer exists; start again")
    await set_actor(auth_request.approved_user_id)
    scope = Scope.org(org.id) if org is not None else Scope.instance()
    now = datetime.now(tz=UTC)
    replaced = await verify_access_key(credentials.credentials) if credentials is not None else None
    if replaced is not None:
        await AccessKey.retire_replaced(replaced.credential_id, auth_request.approved_user_id, scope, now)
    _, token = await mint_standing_access_key(auth_request.approved_user_id, scope, auth_request.client_name)
    await auth_request.delete()
    if org is None:
        return Envelope(data=CliAuthPollOut(root=CliAuthInstanceCompleteOut(interval_seconds=CLI_POLL_INTERVAL_SECONDS, token=token)))
    return Envelope(
        data=CliAuthPollOut(root=CliAuthOrgCompleteOut(interval_seconds=CLI_POLL_INTERVAL_SECONDS, token=token, org_id=org.id, org_name=org.name))
    )
