from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException, Request, Response
from sqlmodel import col

from contract import PLAYGROUND_COOKIE, token_hash
from control_plane.authority import ensure_inference_key_owner, is_allowed, readable_workspaces
from control_plane.authz import Permission, Scope, WorkspaceRole
from control_plane.deps import ActorDep, OrgDep, PlaygroundCookie, WorkspaceDep, org_scope, require, workspace_scope
from control_plane.keys import PLAYGROUND_SESSION_TTL, create_inference_key_for_workspace, rotate_playground_session
from control_plane.models import InferenceKey, Org, OrgMembership, PlaygroundSession, User, Workspace, WorkspaceMembership
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.inference_key import InferenceKeyCreatedOut, InferenceKeyIn, InferenceKeyOut, InferenceKeyOwnerOut, InferenceKeyRevokedOut
from control_plane.models.playground_session import PlaygroundSessionEndedOut, PlaygroundSessionReadyOut
from control_plane.models.workspace import WorkspaceCreate, WorkspaceOut, WorkspaceUpdate
from control_plane.models.workspace_membership import WorkspaceMemberCandidateOut, WorkspaceMembershipIn, WorkspaceMembershipOut
from control_plane.routes.provider_credentials import secret_store

router = APIRouter(prefix="/organizations/{org_id}/workspaces")


def _set_playground_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        PLAYGROUND_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
        max_age=int(PLAYGROUND_SESSION_TTL.total_seconds()),
    )


@router.post("", tags=["Organization Workspaces"], dependencies=[require("api", org_scope, Permission.workspaces_create)])
async def create_workspace(body: WorkspaceCreate, org_id: OrgDep, actor: ActorDep) -> Envelope[WorkspaceOut]:
    """Create a workspace and make the creator its first admin when they belong to the organization.

    The slug is derived from the name when omitted and must be unique within the organization.
    """
    if await Org.find_by_id(org_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if body.slug and await Workspace.slug_taken(org_id, body.slug):
        raise HTTPException(status_code=409, detail="slug is already taken in this org")
    slug = body.slug or await Workspace.free_slug(org_id, body.name)
    workspace = await Workspace(org_id=org_id, name=body.name, slug=slug).save()
    if await OrgMembership.get((actor.principal_id, org_id)) is not None:
        await WorkspaceMembership(user_id=actor.principal_id, workspace_id=workspace.id, org_id=org_id, role=WorkspaceRole.admin).save()
    return Envelope(data=WorkspaceOut.model_validate(workspace))


@router.get(
    "",
    tags=["Organization Workspaces"],
    dependencies=[require("api", org_scope, Permission.workspaces_read, Permission.organizations_read)],
)
async def list_workspaces(org_id: OrgDep, actor: ActorDep) -> Envelope[list[WorkspaceOut]]:
    """List workspaces the caller can read in an organization."""
    visible = await readable_workspaces(actor, org_id)
    return Envelope(data=[WorkspaceOut.model_validate(workspace) for workspace in visible])


@router.get("/{workspace_ref}", tags=["Workspace Settings"], dependencies=[require("api", workspace_scope, Permission.workspaces_read)])
async def get_workspace(workspace: WorkspaceDep) -> Envelope[WorkspaceOut]:
    """Return a workspace by ID or slug."""
    return Envelope(data=WorkspaceOut.model_validate(workspace))


@router.delete("/{workspace_ref}", tags=["Workspace Settings"], dependencies=[require("api", workspace_scope, Permission.workspaces_delete)])
async def delete_workspace(workspace: WorkspaceDep, request: Request) -> Envelope[DeletedOut[UUID]]:
    """Delete a workspace, its memberships, inference keys, and provider credentials.

    Historical usage events are retained.
    """
    await workspace.delete_with_contents(secret_store(request))
    return Envelope(data=DeletedOut.of(workspace.id))


@router.patch("/{workspace_ref}", tags=["Workspace Settings"], dependencies=[require("api", workspace_scope, Permission.workspaces_update)])
async def update_workspace(body: WorkspaceUpdate, workspace: WorkspaceDep) -> Envelope[WorkspaceOut]:
    """Update a workspace's name or slug."""
    return Envelope(data=WorkspaceOut.model_validate(await workspace.apply(body).save()))


@router.get("/{workspace_ref}/policy-users", tags=["Workspace Policies"], dependencies=[require("api", workspace_scope, Permission.policies_read)])
async def list_policy_users(workspace: WorkspaceDep) -> Envelope[list[WorkspaceMemberCandidateOut]]:
    users = await User.policy_candidates(workspace.org_id, workspace.id)
    return Envelope(
        data=[WorkspaceMemberCandidateOut(user_id=user.id, email=user.email, name=user.name, service_account=user.service_account) for user in users]
    )


@router.get("/{workspace_ref}/members", tags=["Workspace Members"], dependencies=[require("api", workspace_scope, Permission.members_read)])
async def list_members(workspace: WorkspaceDep) -> Envelope[list[WorkspaceMembershipOut]]:
    """List the members of a workspace and their workspace roles."""
    memberships = await User.workspace_members(workspace.id)
    return Envelope(
        data=[
            WorkspaceMembershipOut(
                user_id=user.id,
                workspace_id=workspace.id,
                email=user.email,
                name=user.name,
                service_account=user.service_account,
                role=membership.role,
                status="member",
            )
            for membership, user in memberships
        ]
    )


@router.get(
    "/{workspace_ref}/member-candidates",
    tags=["Workspace Members"],
    dependencies=[require("api", workspace_scope, Permission.members_manage)],
)
async def list_member_candidates(workspace: WorkspaceDep) -> Envelope[list[WorkspaceMemberCandidateOut]]:
    """List organization members who can be added to a workspace."""
    candidates = await User.candidates_for_workspace(workspace.org_id, workspace.id)
    return Envelope(
        data=[
            WorkspaceMemberCandidateOut(user_id=user.id, email=user.email, name=user.name, service_account=user.service_account)
            for user in candidates
        ]
    )


@router.put(
    "/{workspace_ref}/members/{user_id}", tags=["Workspace Members"], dependencies=[require("api", workspace_scope, Permission.members_manage)]
)
async def add_member(user_id: UUID, body: WorkspaceMembershipIn, workspace: WorkspaceDep) -> Envelope[WorkspaceMembershipOut]:
    """Add or update a workspace member who already belongs to the organization."""
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if await OrgMembership.get((user_id, workspace.org_id)) is None:
        raise HTTPException(status_code=409, detail="user is not a member of the org")
    membership = await WorkspaceMembership.get((user_id, workspace.id))
    if membership is None:
        membership = WorkspaceMembership(user_id=user_id, workspace_id=workspace.id, org_id=workspace.org_id, role=body.role)
    else:
        membership.role = body.role
    await membership.save()
    return Envelope(
        data=WorkspaceMembershipOut(
            user_id=user_id,
            workspace_id=workspace.id,
            email=user.email,
            name=user.name,
            service_account=user.service_account,
            role=membership.role,
            status="member",
        )
    )


@router.delete(
    "/{workspace_ref}/members/{user_id}", tags=["Workspace Members"], dependencies=[require("api", workspace_scope, Permission.members_manage)]
)
async def remove_member(user_id: UUID, workspace: WorkspaceDep) -> Envelope[DeletedOut[str]]:
    """Remove a member from a workspace without changing organization membership."""
    membership = await WorkspaceMembership.get((user_id, workspace.id))
    if membership is None:
        raise HTTPException(status_code=404, detail="User is not a member of this workspace")
    await membership.remove()
    return Envelope(data=DeletedOut.of(f"{user_id}/{workspace.id}"))


@router.put(
    "/{workspace_ref}/playground-session",
    tags=["Workspace Playground"],
    dependencies=[require("api", workspace_scope, Permission.playground_execute)],
)
async def ensure_playground_session(
    workspace: WorkspaceDep,
    actor: ActorDep,
    request: Request,
    response: Response,
    playground_cookie: PlaygroundCookie = None,
) -> Envelope[PlaygroundSessionReadyOut]:
    """Reuse the browser's short-lived playground session or rotate it into this workspace."""
    now = datetime.now(tz=UTC)
    playground_session = (
        await PlaygroundSession.by_token(actor.credential_id, token_hash(playground_cookie)) if playground_cookie is not None else None
    )
    if playground_session is None or playground_session.workspace_id != workspace.id or not playground_session.active(now):
        playground_session, token = await rotate_playground_session(
            workspace.org_id,
            workspace.id,
            actor.principal_id,
            actor.credential_id,
            now,
        )
        _set_playground_cookie(response, token, request)
    return Envelope(data=PlaygroundSessionReadyOut(id=playground_session.id, expires_at=playground_session.expires_at, status="ready"))


@router.delete(
    "/{workspace_ref}/playground-session",
    tags=["Workspace Playground"],
    dependencies=[require("api", workspace_scope, Permission.playground_execute)],
)
async def end_playground_session(
    workspace: WorkspaceDep,
    actor: ActorDep,
    response: Response,
    playground_cookie: PlaygroundCookie = None,
) -> Envelope[PlaygroundSessionEndedOut]:
    """Revoke the current browser playground session and clear its credential cookie."""
    playground_session = (
        await PlaygroundSession.by_token(actor.credential_id, token_hash(playground_cookie)) if playground_cookie is not None else None
    )
    if playground_session is not None and playground_session.workspace_id == workspace.id:
        playground_session.revoked = True
        await playground_session.save()
    response.delete_cookie(PLAYGROUND_COOKIE, path="/")
    return Envelope(data=PlaygroundSessionEndedOut(status="ended"))


@router.post(
    "/{workspace_ref}/inference-keys",
    tags=["Workspace Inference Keys"],
    dependencies=[require("api", workspace_scope, Permission.inference_keys_manage)],
)
async def create_inference_key(body: InferenceKeyIn, workspace: WorkspaceDep, actor: ActorDep) -> Envelope[InferenceKeyCreatedOut]:
    """Create an inference key for model requests to this workspace and return its token once."""
    await ensure_inference_key_owner(actor, body.user_id, Scope.workspace(workspace.org_id, workspace.id))
    key_id, token = await create_inference_key_for_workspace(workspace.org_id, workspace.id, body.user_id, label=body.label)
    return Envelope(data=InferenceKeyCreatedOut(id=key_id, token=token))


@router.get(
    "/{workspace_ref}/inference-key-owners",
    tags=["Workspace Inference Keys"],
    dependencies=[require("api", workspace_scope, Permission.inference_keys_manage)],
)
async def list_inference_key_owners(workspace: WorkspaceDep, actor: ActorDep) -> Envelope[list[InferenceKeyOwnerOut]]:
    """List principals the caller may select as an inference-key owner."""
    current = await User.find_by_id(actor.principal_id)
    owners = [current] if current is not None else []
    if await is_allowed(actor, Permission.members_manage, Scope.workspace(workspace.org_id, workspace.id)):
        managed = await User.find(User.managing_org_id == workspace.org_id, col(User.service_account).is_(True), order_by=col(User.name))
        owners = [*owners, *(owner for owner in managed if owner.id != actor.principal_id)]
    return Envelope(
        data=[InferenceKeyOwnerOut(user_id=owner.id, email=owner.email, name=owner.name, service_account=owner.service_account) for owner in owners]
    )


@router.get(
    "/{workspace_ref}/inference-keys",
    tags=["Workspace Inference Keys"],
    dependencies=[require("api", workspace_scope, Permission.inference_keys_read)],
)
async def list_inference_keys(workspace: WorkspaceDep) -> Envelope[list[InferenceKeyOut]]:
    """List inference-key metadata for a workspace without returning secret tokens."""
    keys = await InferenceKey.find(InferenceKey.workspace_id == workspace.id, order_by=col(InferenceKey.id))
    return Envelope(data=[InferenceKeyOut.model_validate(k) for k in keys])


@router.delete(
    "/{workspace_ref}/inference-keys/{key_id}",
    tags=["Workspace Inference Keys"],
    dependencies=[require("api", workspace_scope, Permission.inference_keys_manage)],
)
async def revoke_inference_key(workspace: WorkspaceDep, key_id: UUID) -> Envelope[InferenceKeyRevokedOut]:
    """Revoke an inference key in a workspace."""
    key = await InferenceKey.in_workspace(workspace.org_id, workspace.id, key_id)
    key.revoked = True
    await key.save()
    return Envelope(data=InferenceKeyRevokedOut(id=key_id, status="revoked"))
