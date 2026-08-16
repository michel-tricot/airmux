from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Protocol, cast
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, Request, params
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from control_plane.authz import ALL_PERMISSIONS, Authority, Boundary, Permission, Target
from control_plane.db import transaction
from control_plane.keys import verify_bearer
from control_plane.models import Org, User, Workspace, set_actor
from control_plane.sessions import SESSION_COOKIE, verify_session

SessionCookie = Annotated[str | None, Cookie(alias=SESSION_COOKIE, include_in_schema=False)]
OrgHeader = Annotated[str | None, Header(alias="X-Org-Id")]
RequestedWith = Annotated[str | None, Header(alias="X-Requested-With", include_in_schema=False)]
FetchSite = Annotated[str | None, Header(alias="Sec-Fetch-Site", include_in_schema=False)]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from control_plane.models import AuthSession

_bearer = HTTPBearer(auto_error=False)

BearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def require_csrf(x_requested_with: str | None, sec_fetch_site: str | None) -> None:
    if x_requested_with is None:
        raise HTTPException(status_code=403, detail="Missing X-Requested-With")
    if sec_fetch_site is not None and sec_fetch_site not in ("same-origin", "none"):
        raise HTTPException(status_code=403, detail="Cross-site request rejected")


async def _session_user(session_cookie: str, x_requested_with: str | None, sec_fetch_site: str | None) -> tuple[AuthSession, User]:
    require_csrf(x_requested_with, sec_fetch_site)
    auth_session = await verify_session(session_cookie)
    if auth_session is None:
        raise HTTPException(status_code=401, detail="Your session has expired; sign in again")
    user = await User.find_by_id(auth_session.user_id)
    if user is None or user.service_account:
        raise HTTPException(status_code=401, detail="This account no longer exists; sign in again")
    return auth_session, user


async def authority(
    credentials: BearerDep,
    session_cookie: SessionCookie = None,
    x_requested_with: RequestedWith = None,
    sec_fetch_site: FetchSite = None,
) -> Authority:
    if credentials is not None:
        resolved = await verify_bearer(credentials.credentials)
        if resolved is None:
            raise HTTPException(status_code=401, detail="Invalid, expired, or revoked credential")
    elif session_cookie is not None:
        auth_session, user = await _session_user(session_cookie, x_requested_with, sec_fetch_site)
        resolved = Authority(
            credential_id=auth_session.id,
            principal_id=user.id,
            credential_kind="session",
            permission_ceiling=ALL_PERMISSIONS,
        )
    else:
        raise HTTPException(status_code=401, detail="Authentication required; sign in or provide a credential")
    await set_actor(resolved.principal_id)
    return resolved


AuthorityDep = Annotated[Authority, Depends(authority)]


async def acting_user(resolved: AuthorityDep) -> User:
    user = await User.find_by_id(resolved.principal_id)
    if user is None or user.service_account:
        raise HTTPException(status_code=401, detail="This credential's account no longer exists")
    return user


ActingUserDep = Annotated[User, Depends(acting_user)]


async def cookie_user(
    session_cookie: SessionCookie = None,
    x_requested_with: RequestedWith = None,
    sec_fetch_site: FetchSite = None,
) -> User:
    if session_cookie is None:
        raise HTTPException(status_code=401, detail="Sign in to approve this request; a key cannot be used here")
    _, user = await _session_user(session_cookie, x_requested_with, sec_fetch_site)
    await set_actor(user.id)
    return user


CookieUserDep = Annotated[User, Depends(cookie_user)]


def _org_header(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(status_code=403, detail="X-Org-Id is not a valid organization id") from None


async def selected_org(authority: AuthorityDep, x_org_id: OrgHeader = None) -> UUID:
    requested = _org_header(x_org_id)
    if authority.boundary in {Boundary.org, Boundary.workspace}:
        if requested is not None and requested != authority.org_id:
            raise HTTPException(status_code=403, detail="The credential is bound to a different organization")
        org_id = authority.org_id
    else:
        org_id = requested
    if org_id is None:
        raise HTTPException(status_code=403, detail="X-Org-Id required")
    if await Org.find_by_id(org_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org_id


OrgDep = Annotated[UUID, Depends(selected_org)]


async def selected_workspace(workspace_ref: str, org_id: OrgDep) -> Workspace:
    return await Workspace.by_ref(org_id, workspace_ref)


WorkspaceDep = Annotated[Workspace, Depends(selected_workspace)]


async def instance_target() -> Target:
    return Target.instance()


async def org_target(org_id: OrgDep) -> Target:
    return Target.org(org_id)


async def named_org_target(org_id: UUID) -> Target:
    return Target.org(org_id)


async def workspace_target(workspace: WorkspaceDep) -> Target:
    return Target.workspace(workspace.org_id, workspace.id)


async def selected_target(authority: AuthorityDep, x_org_id: OrgHeader = None) -> Target:
    if authority.boundary is not None:
        return Target(level=authority.boundary, org_id=authority.org_id, workspace_id=authority.workspace_id)
    org_id = _org_header(x_org_id)
    if org_id is None:
        return Target.instance()
    if await Org.find_by_id(org_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return Target.org(org_id)


async def authorize(authority: Authority, permission: Permission, target: Target) -> None:
    if not await authority.allows(permission, target):
        raise HTTPException(status_code=403, detail=f"authority lacks {permission.value} at the {target.level.value} boundary")


class PermissionCheck(Protocol):
    required_permission: Permission
    required_target: str

    def __call__(self, authority: Authority) -> Awaitable[None]: ...


def require(permission: Permission, target_resolver: Callable[..., Awaitable[Target]]) -> params.Depends:
    target_dependency = Depends(target_resolver)

    async def check_permission(authority: AuthorityDep, target: Target = target_dependency) -> None:
        await authorize(authority, permission, target)

    checker = cast("PermissionCheck", check_permission)
    checker.required_permission = permission
    target_name = getattr(target_resolver, "__name__", "")
    checker.required_target = target_name if isinstance(target_name, str) else type(target_resolver).__name__
    return Depends(checker)


class AccessTag(Protocol):
    access: str

    def __call__(self) -> Awaitable[None]: ...


def _access_marker(kind: str) -> params.Depends:
    async def access_marker() -> None: ...

    tagged = cast("AccessTag", access_marker)
    tagged.access = kind
    return Depends(tagged)


def public() -> params.Depends:
    return _access_marker("public")


def user_scoped() -> params.Depends:
    return _access_marker("user")


def browser_scoped() -> params.Depends:
    return _access_marker("browser")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with transaction(request.app.state.session_factory) as session:
        yield session


SessionDep = Annotated["AsyncSession", Depends(get_session, scope="function")]
