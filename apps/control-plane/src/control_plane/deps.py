from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Protocol, cast
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Request, params
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from contract import PLAYGROUND_COOKIE
from control_plane.authority import effective_permissions
from control_plane.authz import ALL_PERMISSIONS, Actor, Grant, Permission, Scope
from control_plane.db import transaction
from control_plane.keys import verify_bearer
from control_plane.models import Org, User, Workspace, set_actor
from control_plane.models.runtime_configuration import RuntimeConfiguration, runtime_configuration_changes
from control_plane.sessions import SESSION_COOKIE, verify_session

SessionCookie = Annotated[str | None, Cookie(alias=SESSION_COOKIE, include_in_schema=False)]
PlaygroundCookie = Annotated[str | None, Cookie(alias=PLAYGROUND_COOKIE, include_in_schema=False)]
RequestedWith = Annotated[str | None, params.Header(alias="X-Requested-With", include_in_schema=False)]
FetchSite = Annotated[str | None, params.Header(alias="Sec-Fetch-Site", include_in_schema=False)]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession

    from control_plane.models import AuthSession

_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="AccessKey",
    description="A control-plane access key using the `sk-cp-` prefix. Inference keys are not accepted by control-plane endpoints.",
)

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


async def actor(
    credentials: BearerDep,
    session_cookie: SessionCookie = None,
    x_requested_with: RequestedWith = None,
    sec_fetch_site: FetchSite = None,
) -> Actor:
    if credentials is not None:
        resolved = await verify_bearer(credentials.credentials)
        if resolved is None:
            raise HTTPException(status_code=401, detail="Invalid, expired, or revoked credential")
    elif session_cookie is not None:
        auth_session, user = await _session_user(session_cookie, x_requested_with, sec_fetch_site)
        resolved = Actor(
            credential_id=auth_session.id,
            principal_id=user.id,
            credential_kind="session",
            grant=Grant(scope=Scope.instance(), permissions=ALL_PERMISSIONS),
        )
    else:
        raise HTTPException(status_code=401, detail="Authentication required; sign in or provide a credential")
    await set_actor(resolved.principal_id)
    return resolved


ActorDep = Annotated[Actor, Depends(actor)]


async def acting_user(resolved: ActorDep) -> User:
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


async def selected_org(org_id: str) -> UUID:
    org = await Org.by_ref(org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org.id


OrgDep = Annotated[UUID, Depends(selected_org)]


async def selected_workspace(workspace_ref: str, org_id: OrgDep) -> Workspace:
    return await Workspace.by_ref(org_id, workspace_ref)


WorkspaceDep = Annotated[Workspace, Depends(selected_workspace)]


async def instance_scope() -> Scope:
    return Scope.instance()


async def org_scope(org_id: OrgDep) -> Scope:
    return Scope.org(org_id)


async def workspace_scope(workspace: WorkspaceDep) -> Scope:
    return Scope.workspace(workspace.org_id, workspace.id)


async def credential_scope(resolved: ActorDep) -> Scope:
    return resolved.grant.scope


CredentialScopeDep = Annotated[Scope, Depends(credential_scope)]


async def bundle_scope(resolved: ActorDep, org_id: UUID | None = None) -> Scope:
    selected = org_id
    if selected is None and resolved.grant.scope.org_id is not None:
        selected = resolved.grant.scope.org_id
    if selected is None:
        return Scope.instance()
    if await Org.find_by_id(selected) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return Scope.org(selected)


BundleScopeDep = Annotated[Scope, Depends(bundle_scope)]


async def permission_scope(org_id: UUID | None = None, workspace_ref: str | None = None) -> Scope:
    if workspace_ref is not None and org_id is None:
        raise HTTPException(status_code=422, detail="workspace_ref requires org_id")
    if org_id is None:
        return Scope.instance()
    if await Org.find_by_id(org_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if workspace_ref is not None:
        workspace = await Workspace.by_ref(org_id, workspace_ref)
        return Scope.workspace(org_id, workspace.id)
    return Scope.org(org_id)


PermissionScopeDep = Annotated[Scope, Depends(permission_scope)]


class PermissionCheck(Protocol):
    required_permissions: tuple[Permission, ...]
    required_scope: str

    def __call__(self, actor: Actor) -> Awaitable[None]: ...


def require(scope_resolver: Callable[..., Awaitable[Scope]], permission: Permission, *additional_permissions: Permission) -> params.Depends:
    required = (permission, *additional_permissions)
    scope_dependency = Depends(scope_resolver)

    async def check_permission(resolved: ActorDep, scope: Scope = scope_dependency) -> None:
        effective = await effective_permissions(resolved, scope)
        if any(permission in effective for permission in required):
            return
        names = ", ".join(permission.value for permission in required)
        detail = (
            f"Missing {names} permission for {scope.level.value} scope"
            if len(required) == 1
            else f"Missing one of {names} permissions for {scope.level.value} scope"
        )
        raise HTTPException(status_code=403, detail=detail)

    checker = cast("PermissionCheck", check_permission)
    checker.required_permissions = required
    scope_name = getattr(scope_resolver, "__name__", "")
    checker.required_scope = scope_name if isinstance(scope_name, str) else type(scope_resolver).__name__
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


def principal_scoped() -> params.Depends:
    return _access_marker("principal")


def browser_scoped() -> params.Depends:
    return _access_marker("browser")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with transaction(request.app.state.session_factory) as session:
        yield session
        changes = runtime_configuration_changes(session.sync_session)
        if changes:
            from control_plane.compiler import publish_pending  # noqa: PLC0415 compiler loads every projected model

            settings = request.app.state.settings
            await RuntimeConfiguration.advance(changes)
            await publish_pending(datetime.now(tz=UTC), settings.bundle.signing_key)


SessionDep = Annotated["AsyncSession", Depends(get_session, scope="function")]
