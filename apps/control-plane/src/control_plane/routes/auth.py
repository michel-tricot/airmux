from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Literal
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from authlib.jose import JoseError, JsonWebToken
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from authlib.oidc.core import CodeIDToken
from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response
from joserfc.errors import JoseError as JoseRfcError
from pydantic import BaseModel, Field

from control_plane.db import current_actor
from control_plane.deps import BearerDep, SessionDep, public, require_csrf, user_scoped
from control_plane.models import AuthIdentity, LoginAttempt, OrgMembership, SsoConnection, User
from control_plane.passwords import DUMMY_HASH, hash_password, needs_rehash, verify_password
from control_plane.schemas import DeletedOut, Envelope
from control_plane.sessions import SESSION_ABSOLUTE_TTL, SESSION_COOKIE, aware, mint_session, verify_session
from control_plane.tokens import verify_management_token

if TYPE_CHECKING:
    from control_plane.config import Settings

router = APIRouter(prefix="/auth")

_jwt = JsonWebToken(["RS256", "ES256"])

PASSWORD_PROVIDER = "password"  # noqa: S105 provider discriminator, not a secret

SessionCookie = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]
RequestedWith = Annotated[str | None, Header(alias="X-Requested-With")]
FetchSite = Annotated[str | None, Header(alias="Sec-Fetch-Site")]


class DiscoverIn(BaseModel):
    email: str


class DiscoverOut(BaseModel):
    method: Literal["password", "sso"]
    connection_id: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class SignupIn(BaseModel):
    email: str
    name: str = ""
    password: str = Field(min_length=8)


class MeOut(BaseModel):
    user_id: str
    email: str
    name: str
    instance_admin: bool
    orgs: list[str]


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class PasswordChangedOut(BaseModel):
    user_id: str
    status: Literal["changed"]


class SsoStartIn(BaseModel):
    connection_id: str


class SsoStartOut(BaseModel):
    authorize_url: str


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


def _redirect_uri(settings: Settings) -> str:
    return settings.auth.public_base_url.rstrip("/") + "/v1/auth/sso/callback"


async def _me_out(user: User) -> MeOut:
    memberships = await OrgMembership.find(OrgMembership.user_id == user.id)
    return MeOut(user_id=user.id, email=user.email, name=user.name, instance_admin=user.instance_admin, orgs=sorted(m.org_id for m in memberships))


async def _login_user(email: str, password: str) -> User:
    """Password verification with one 401 for every failure shape, so responses never say which part was wrong."""
    identity = await AuthIdentity.first(AuthIdentity.provider == PASSWORD_PROVIDER, AuthIdentity.subject == email.lower())
    if identity is None or identity.secret_hash is None:
        verify_password(DUMMY_HASH, password)
        raise HTTPException(status_code=401)
    if not verify_password(identity.secret_hash, password):
        raise HTTPException(status_code=401)
    user = await User.get(identity.user_id)
    if user is None or user.service_account:
        raise HTTPException(status_code=401)
    if needs_rehash(identity.secret_hash):
        identity.secret_hash = hash_password(password)
        await identity.save()
    return user


async def _acting_user(credentials: BearerDep, session_cookie: SessionCookie, x_requested_with: RequestedWith, sec_fetch_site: FetchSite) -> User:
    """User-level resolution for account endpoints: either door, no org scope involved."""
    if credentials is not None:
        claims = await verify_management_token(credentials.credentials)
        if claims is None:
            raise HTTPException(status_code=401)
        user = await User.get(claims.user_id)
    elif session_cookie is not None:
        require_csrf(x_requested_with, sec_fetch_site)
        row = await verify_session(session_cookie)
        if row is None:
            raise HTTPException(status_code=401)
        user = await User.get(row.user_id)
    else:
        raise HTTPException(status_code=401)
    if user is None or user.service_account:
        raise HTTPException(status_code=401)
    current_actor.set(user.id)
    return user


async def _sso_connection_for(email: str) -> SsoConnection | None:
    domain = email.rsplit("@", 1)[-1].lower()
    for connection in await SsoConnection.find():
        if domain in (d.lower() for d in connection.email_domains):
            return connection
    return None


@router.post("/discover", tags=["Auth"], dependencies=[public()])
async def discover(body: DiscoverIn, _session: SessionDep) -> Envelope[DiscoverOut]:
    """Home-realm discovery: purely domain-driven, so it never reveals whether a user exists."""
    connection = await _sso_connection_for(body.email)
    if connection is not None:
        return Envelope(data=DiscoverOut(method="sso", connection_id=connection.id))
    return Envelope(data=DiscoverOut(method="password"))


@router.post("/login", tags=["Auth"], dependencies=[public()])
async def login(body: LoginIn, request: Request, response: Response, _session: SessionDep) -> Envelope[MeOut]:
    user = await _login_user(body.email, body.password)
    current_actor.set(user.id)
    _, token = await mint_session(user.id)
    _set_session_cookie(response, token, request.app.state.settings)
    return Envelope(data=await _me_out(user))


@router.post("/signup", tags=["Auth"], dependencies=[public()])
async def signup(body: SignupIn, request: Request, response: Response, _session: SessionDep) -> Envelope[MeOut]:
    """Open self-signup: a fresh account holds no memberships and no admin bit, so it can see nothing until granted."""
    if await _sso_connection_for(body.email) is not None:
        raise HTTPException(status_code=403, detail="this domain signs in with SSO")
    if await User.first(User.email == body.email) is not None:
        raise HTTPException(status_code=409)
    user = User(id=f"u-{uuid4().hex[:8]}", email=body.email, name=body.name or body.email, instance_admin=False, service_account=False)
    current_actor.set(user.id)
    await user.save()
    await AuthIdentity(
        id=f"ai-{uuid4().hex[:8]}", user_id=user.id, provider=PASSWORD_PROVIDER, subject=body.email.lower(), secret_hash=hash_password(body.password)
    ).save()
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
) -> Envelope[DeletedOut[str]]:
    if session_cookie is None:
        raise HTTPException(status_code=401)
    require_csrf(x_requested_with, sec_fetch_site)
    row = await verify_session(session_cookie)
    if row is None:
        raise HTTPException(status_code=401)
    current_actor.set(row.user_id)
    await row.delete()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return Envelope(data=DeletedOut(id=row.id, deleted_at=datetime.now(tz=UTC)))


@router.get("/me", tags=["Auth"], dependencies=[user_scoped()])
async def me(
    _session: SessionDep,
    credentials: BearerDep = None,
    session_cookie: SessionCookie = None,
    x_requested_with: RequestedWith = None,
    sec_fetch_site: FetchSite = None,
) -> Envelope[MeOut]:
    user = await _acting_user(credentials, session_cookie, x_requested_with, sec_fetch_site)
    return Envelope(data=await _me_out(user))


@router.post("/password", tags=["Auth"], dependencies=[user_scoped()])
async def change_password(
    body: PasswordChangeIn,
    _session: SessionDep,
    credentials: BearerDep = None,
    session_cookie: SessionCookie = None,
    x_requested_with: RequestedWith = None,
    sec_fetch_site: FetchSite = None,
) -> Envelope[PasswordChangedOut]:
    user = await _acting_user(credentials, session_cookie, x_requested_with, sec_fetch_site)
    identity = await AuthIdentity.first(AuthIdentity.provider == PASSWORD_PROVIDER, AuthIdentity.subject == user.email.lower())
    if identity is None or identity.secret_hash is None or not verify_password(identity.secret_hash, body.current_password):
        raise HTTPException(status_code=403)
    identity.secret_hash = hash_password(body.new_password)
    await identity.save()
    return Envelope(data=PasswordChangedOut(user_id=user.id, status="changed"))


@router.post("/sso/start", tags=["Auth"], dependencies=[public()])
async def sso_start(body: SsoStartIn, request: Request, _session: SessionDep) -> Envelope[SsoStartOut]:
    connection = await SsoConnection.get(body.connection_id)
    if connection is None:
        raise HTTPException(status_code=404)
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(16), secrets.token_urlsafe(48)
    await LoginAttempt(
        state=state, connection_id=connection.id, nonce=nonce, code_verifier=verifier, expires_at=datetime.now(tz=UTC) + timedelta(minutes=10)
    ).save()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": connection.client_id,
            "redirect_uri": _redirect_uri(request.app.state.settings),
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": create_s256_code_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    return Envelope(data=SsoStartOut(authorize_url=f"{connection.authorization_endpoint}?{query}"))


async def _exchange_and_validate(connection: SsoConnection, code: str, verifier: str, nonce: str, settings: Settings) -> dict:
    async with httpx.AsyncClient(timeout=10) as http:
        token_resp = await http.post(
            connection.token_endpoint,
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": _redirect_uri(settings), "code_verifier": verifier},
            auth=(connection.client_id, connection.client_secret),
        )
        if not token_resp.is_success:
            raise HTTPException(status_code=401)
        id_token = token_resp.json().get("id_token")
        if not isinstance(id_token, str):
            raise HTTPException(status_code=401)
        jwks_resp = await http.get(connection.jwks_uri)
        if not jwks_resp.is_success:
            raise HTTPException(status_code=502)
        jwks = jwks_resp.json()
    try:
        claims = _jwt.decode(
            id_token,
            jwks,
            claims_cls=CodeIDToken,
            claims_options={
                "iss": {"essential": True, "values": [connection.issuer]},
                "aud": {"essential": True, "values": [connection.client_id]},
            },
            claims_params={"nonce": nonce},
        )
        claims.validate(leeway=120)
    except (JoseError, JoseRfcError) as e:
        raise HTTPException(status_code=401) from e
    return dict(claims)


async def _resolve_sso_user(connection: SsoConnection, claims: dict) -> User:
    provider = f"oidc:{connection.id}"
    subject = str(claims["sub"])
    identity = await AuthIdentity.first(AuthIdentity.provider == provider, AuthIdentity.subject == subject)
    if identity is not None:
        user = await User.get(identity.user_id)
        if user is None or user.service_account:
            raise HTTPException(status_code=403)
        return user
    email = claims.get("email")
    user = await User.first(User.email == email) if email else None
    if user is not None and user.service_account:
        raise HTTPException(status_code=403)
    if user is None:
        if not connection.jit or not email:
            raise HTTPException(status_code=403)
        user = User(id=f"u-{uuid4().hex[:8]}", email=email, name=str(claims.get("name") or email), instance_admin=False, service_account=False)
        current_actor.set(user.id)
        await user.save()
    current_actor.set(user.id)
    if await OrgMembership.get((user.id, connection.org_id)) is None:
        await OrgMembership(user_id=user.id, org_id=connection.org_id).save()
    await AuthIdentity(id=f"ai-{uuid4().hex[:8]}", user_id=user.id, provider=provider, subject=subject).save()
    return user


@router.get("/sso/callback", tags=["Auth"], dependencies=[public()])
async def sso_callback(state: str, code: str, request: Request, response: Response, _session: SessionDep) -> Envelope[MeOut]:
    attempt = await LoginAttempt.get(state)
    if attempt is None or aware(attempt.expires_at) <= datetime.now(tz=UTC):
        raise HTTPException(status_code=400)
    await attempt.delete()
    connection = await SsoConnection.get(attempt.connection_id)
    if connection is None:
        raise HTTPException(status_code=400)
    settings = request.app.state.settings
    claims = await _exchange_and_validate(connection, code, attempt.code_verifier, attempt.nonce, settings)
    user = await _resolve_sso_user(connection, claims)
    _, token = await mint_session(user.id)
    _set_session_cookie(response, token, settings)
    return Envelope(data=await _me_out(user))
