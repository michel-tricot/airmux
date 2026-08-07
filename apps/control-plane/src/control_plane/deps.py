from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol, cast

from fastapi import Cookie, Depends, Header, HTTPException, Request, params
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from control_plane.authz import Scope, allowed
from control_plane.db import current_actor, transaction
from control_plane.models import Org, OrgMembership, User
from control_plane.sessions import SESSION_COOKIE, verify_session
from control_plane.tokens import ManagementClaims, verify_management_token

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable

    from sqlalchemy.ext.asyncio import AsyncSession

_bearer = HTTPBearer(auto_error=False)

BearerDep = Annotated["HTTPAuthorizationCredentials | None", Depends(_bearer)]


def require_csrf(x_requested_with: str | None, sec_fetch_site: str | None) -> None:
    """Cookie-door requests only: the custom header cannot be attached cross-origin without CORS
    approval, and Sec-Fetch-Site is the browser's own cross-site declaration. Bearer requests are
    immune by construction and never checked."""
    if x_requested_with is None:
        raise HTTPException(status_code=403, detail="Missing X-Requested-With")
    if sec_fetch_site is not None and sec_fetch_site not in ("same-origin", "none"):
        raise HTTPException(status_code=403, detail="Cross-site request rejected")


async def _cookie_claims(token: str, x_org_id: str | None) -> ManagementClaims:
    """A session is user-scoped; X-Org-Id selects the org scope, backed by the same membership
    rules as key minting. Without it, only instance admins get instance scope."""
    row = await verify_session(token)
    if row is None:
        raise HTTPException(status_code=401)
    user = await User.get(row.user_id)
    if user is None or user.service_account:
        raise HTTPException(status_code=401)
    if x_org_id is None:
        if not user.instance_admin:
            raise HTTPException(status_code=403, detail="X-Org-Id required")
        return ManagementClaims(token_id=row.id, org_id=None, user_id=user.id)
    if await Org.get(x_org_id) is None:
        raise HTTPException(status_code=403)
    if not user.instance_admin and await OrgMembership.get((user.id, x_org_id)) is None:
        raise HTTPException(status_code=403)
    return ManagementClaims(token_id=row.id, org_id=x_org_id, user_id=user.id)


async def management_claims(
    credentials: BearerDep,
    _session: SessionDep,
    session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    x_org_id: Annotated[str | None, Header(alias="X-Org-Id")] = None,
    x_requested_with: Annotated[str | None, Header(alias="X-Requested-With")] = None,
    sec_fetch_site: Annotated[str | None, Header(alias="Sec-Fetch-Site")] = None,
) -> ManagementClaims:
    if credentials is not None:
        claims = await verify_management_token(credentials.credentials)
        if claims is None:
            raise HTTPException(status_code=401)
    elif session_cookie is not None:
        require_csrf(x_requested_with, sec_fetch_site)
        claims = await _cookie_claims(session_cookie, x_org_id)
    else:
        raise HTTPException(status_code=401)
    current_actor.set(claims.user_id)
    return claims


MgmtDep = Annotated[ManagementClaims, Depends(management_claims)]


async def instance_scope(claims: MgmtDep) -> ManagementClaims:
    if claims.org_id is not None:
        raise HTTPException(status_code=403)
    return claims


async def org_scope(claims: MgmtDep) -> str:
    if claims.org_id is None:
        raise HTTPException(status_code=403)
    return claims.org_id


InstanceDep = Annotated[ManagementClaims, Depends(instance_scope)]
OrgDep = Annotated[str, Depends(org_scope)]


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
