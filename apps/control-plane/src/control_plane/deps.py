from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol, cast
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, Request, params
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from control_plane.authz import ALL_SCOPES, Scope, allowed
from control_plane.db import transaction
from control_plane.keys import ManagementClaims, verify_bearer
from control_plane.models import Org, User, Workspace, WorkspaceMembership, set_actor
from control_plane.sessions import SESSION_COOKIE, verify_session

SessionCookie = Annotated[str | None, Cookie(alias=SESSION_COOKIE)]
RequestedWith = Annotated[str | None, Header(alias="X-Requested-With")]
FetchSite = Annotated[str | None, Header(alias="Sec-Fetch-Site")]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable

    from sqlalchemy.ext.asyncio import AsyncSession

    from control_plane.models import AuthSession

_bearer = HTTPBearer(auto_error=False)

BearerDep = Annotated["HTTPAuthorizationCredentials | None", Depends(_bearer)]


def require_csrf(x_requested_with: str | None, sec_fetch_site: str | None) -> None:
    """Cookie-door requests only: the custom header cannot be attached cross-origin without CORS
    approval, and Sec-Fetch-Site is the browser's own cross-site declaration."""
    if x_requested_with is None:
        raise HTTPException(status_code=403, detail="Missing X-Requested-With")
    if sec_fetch_site is not None and sec_fetch_site not in ("same-origin", "none"):
        raise HTTPException(status_code=403, detail="Cross-site request rejected")


async def _session_user(session_cookie: str, x_requested_with: str | None, sec_fetch_site: str | None) -> tuple[AuthSession, User]:
    """Cookie-door resolution shared by the org-scoped and user-scoped deps: CSRF, a live session, a human user."""
    require_csrf(x_requested_with, sec_fetch_site)
    auth_session = await verify_session(session_cookie)
    if auth_session is None:
        raise HTTPException(status_code=401)
    user = await User.find_by_id(auth_session.user_id)
    if user is None or user.service_account:
        raise HTTPException(status_code=401)
    return auth_session, user


async def _cookie_claims(auth_session: AuthSession, user: User, x_org_id: str | None) -> ManagementClaims:
    """A session is user-scoped; X-Org-Id selects the org scope, backed by the same membership
    rules as key minting. Without it, only instance admins get instance scope."""
    if x_org_id is None:
        if not user.instance_admin:
            raise HTTPException(status_code=403, detail="X-Org-Id required")
        return ManagementClaims(token_id=auth_session.id, org_id=None, user_id=user.id, scopes=ALL_SCOPES)
    try:
        org_id = UUID(x_org_id)
    except ValueError:
        raise HTTPException(status_code=403) from None
    if await Org.find_by_id(org_id) is None:
        raise HTTPException(status_code=403)
    if not await user.backs_org(org_id):
        raise HTTPException(status_code=403)
    return ManagementClaims(token_id=auth_session.id, org_id=org_id, user_id=user.id, scopes=ALL_SCOPES)


async def management_claims(
    credentials: BearerDep,
    _session: SessionDep,
    session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    x_org_id: Annotated[str | None, Header(alias="X-Org-Id")] = None,
    x_requested_with: Annotated[str | None, Header(alias="X-Requested-With")] = None,
    sec_fetch_site: Annotated[str | None, Header(alias="Sec-Fetch-Site")] = None,
) -> ManagementClaims:
    if credentials is not None:
        claims = await verify_bearer(credentials.credentials)
        if claims is None:
            raise HTTPException(status_code=401)
    elif session_cookie is not None:
        auth_session, user = await _session_user(session_cookie, x_requested_with, sec_fetch_site)
        claims = await _cookie_claims(auth_session, user, x_org_id)
    else:
        raise HTTPException(status_code=401)
    await set_actor(claims.user_id)
    return claims


MgmtDep = Annotated[ManagementClaims, Depends(management_claims)]


async def acting_user(
    credentials: BearerDep,
    _session: SessionDep,
    session_cookie: SessionCookie = None,
    x_requested_with: RequestedWith = None,
    sec_fetch_site: FetchSite = None,
) -> User:
    """User-level resolution for account endpoints: either door, no org scope involved."""
    if credentials is not None:
        claims = await verify_bearer(credentials.credentials)
        if claims is None:
            raise HTTPException(status_code=401)
        user = await User.find_by_id(claims.user_id)
        if user is None or user.service_account:
            raise HTTPException(status_code=401)
    elif session_cookie is not None:
        _, user = await _session_user(session_cookie, x_requested_with, sec_fetch_site)
    else:
        raise HTTPException(status_code=401)
    await set_actor(user.id)
    return user


ActingUserDep = Annotated[User, Depends(acting_user)]


async def cookie_user(
    _session: SessionDep,
    session_cookie: SessionCookie = None,
    x_requested_with: RequestedWith = None,
    sec_fetch_site: FetchSite = None,
) -> User:
    """The cookie door only, for endpoints a bearer key must never reach (device approval): a
    delegated credential can never approve its own successor."""
    if session_cookie is None:
        raise HTTPException(status_code=401)
    _, user = await _session_user(session_cookie, x_requested_with, sec_fetch_site)
    await set_actor(user.id)
    return user


CookieUserDep = Annotated[User, Depends(cookie_user)]


async def instance_scope(claims: MgmtDep) -> ManagementClaims:
    if claims.org_id is not None:
        raise HTTPException(status_code=403)
    return claims


async def org_scope(claims: MgmtDep) -> UUID:
    if claims.org_id is None:
        raise HTTPException(status_code=403)
    return claims.org_id


InstanceDep = Annotated[ManagementClaims, Depends(instance_scope)]
OrgDep = Annotated[UUID, Depends(org_scope)]


async def workspace_member(workspace_id: UUID, org_id: OrgDep, claims: MgmtDep) -> Workspace:
    """Key operations require membership in the workspace, not just the org; instance admins bypass.

    Ownership resolves first, so a workspace outside the org scope is a 404 before it is a 403.
    """
    workspace = await Workspace.owned_by(org_id, workspace_id)
    if await WorkspaceMembership.get((claims.user_id, workspace_id)) is None:
        user = await User.find_by_id(claims.user_id)
        if user is None or not user.instance_admin:
            raise HTTPException(status_code=403, detail="not a member of this workspace")
    return workspace


WorkspaceDep = Annotated[Workspace, Depends(workspace_member)]


class ScopeCheck(Protocol):
    """The checker require() builds: a dependency callable tagged with the scope it enforces,
    so the hygiene test can introspect required_scope on every route and prove coverage."""

    required_scope: Scope

    def __call__(self, claims: ManagementClaims) -> Awaitable[None]: ...


def require(scope: Scope) -> params.Depends:
    async def check_scope(claims: MgmtDep) -> None:
        if not allowed(claims, scope):
            raise HTTPException(status_code=403, detail=f"credential lacks the {scope.value} scope")

    checker = cast("ScopeCheck", check_scope)
    checker.required_scope = scope
    return Depends(checker)


class AccessTag(Protocol):
    """The marker public() and user_scoped() build: a no-op dependency tagging the route's access
    level, so the hygiene test can prove every route declares its authorization exactly once."""

    access: str

    def __call__(self) -> Awaitable[None]: ...


def _access_marker(kind: str) -> params.Depends:
    async def access_marker() -> None: ...

    tagged = cast("AccessTag", access_marker)
    tagged.access = kind
    return Depends(tagged)


def public() -> params.Depends:
    """Deliberately unauthenticated: reachable before any credential exists."""
    return _access_marker("public")


def user_scoped() -> params.Depends:
    """Authenticated user through either door; no org or scope semantics apply."""
    return _access_marker("user")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with transaction(request.app.state.session_factory) as session:
        yield session


SessionDep = Annotated["AsyncSession", Depends(get_session, scope="function")]
