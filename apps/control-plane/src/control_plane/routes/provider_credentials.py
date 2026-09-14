from __future__ import annotations

from typing import Annotated
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, Depends, HTTPException, Request

from contract import Secret, SecretRejectedError, SecretStore
from control_plane.authz import Permission, Scope
from control_plane.deps import OrgDep, WorkspaceDep, instance_scope, org_scope, require, workspace_scope
from control_plane.models import Provider, ProviderCredential, Workspace
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.provider_credential import (
    ProviderCredentialIn,
    ProviderCredentialOut,
    ProviderCredentialUpdate,
    ProviderCredentialValueIn,
)

router = APIRouter(prefix="/organizations/{org_id}")
instance_router = APIRouter(prefix="/instance/provider-credentials")


def secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


async def _provider(name: str) -> Provider:
    provider = await Provider.first(Provider.name == name)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


async def selected_credential(credential_id: UUID, org_id: OrgDep) -> ProviderCredential:
    return await ProviderCredential.in_org(org_id, credential_id)


CredentialDep = Annotated[ProviderCredential, Depends(selected_credential)]


async def credential_scope(credential: CredentialDep) -> Scope:
    if credential.workspace_id is not None:
        if credential.org_id is None:
            raise HTTPException(status_code=500, detail="Credential has an invalid scope")
        return Scope.workspace(credential.org_id, credential.workspace_id)
    if credential.org_id is None:
        return Scope.instance()
    return Scope.org(credential.org_id)


async def _create_provider_credential(
    body: ProviderCredentialIn,
    org_id: UUID | None,
    workspace: Workspace | None,
    request: Request,
) -> Envelope[ProviderCredentialOut]:
    store = secret_store(request)
    provider = await _provider(body.provider)
    workspace_id = workspace.id if workspace else None
    if await ProviderCredential.named(org_id, workspace_id, provider.id, body.name) is not None:
        raise HTTPException(status_code=409, detail="a credential with this name already exists for this provider and scope")
    secret = Secret(body.value.get_secret_value())
    credential = await ProviderCredential(
        org_id=org_id,
        workspace_id=workspace_id,
        provider_id=provider.id,
        provider_name=provider.name,
        name=body.name,
        priority=body.priority,
    ).save()
    credential.fingerprint = await _hold(store, credential, secret)
    return Envelope(data=ProviderCredentialOut.model_validate(await credential.save()))


async def _hold(store: SecretStore, credential: ProviderCredential, secret: Secret) -> str:
    try:
        held = await store.put(credential.secret_ref(), secret)
    except SecretRejectedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    return held.fingerprint


@instance_router.post(
    "",
    tags=["Instance Provider Credentials"],
    dependencies=[require("api", instance_scope, Permission.provider_credentials_manage)],
)
async def create_instance_provider_credential(body: ProviderCredentialIn, request: Request) -> Envelope[ProviderCredentialOut]:
    """Store a provider API key available to every organization on the instance."""
    return await _create_provider_credential(body, None, None, request)


@instance_router.get(
    "",
    tags=["Instance Provider Credentials"],
    dependencies=[require("api", instance_scope, Permission.provider_credentials_read)],
)
async def list_instance_provider_credentials() -> Envelope[list[ProviderCredentialOut]]:
    """List provider credentials owned by the instance."""
    credentials = await ProviderCredential.for_instance()
    return Envelope(data=[ProviderCredentialOut.model_validate(credential) for credential in credentials])


@router.post(
    "/provider-credentials",
    tags=["Organization Provider Credentials"],
    dependencies=[require("api", org_scope, Permission.provider_credentials_manage)],
)
async def create_org_provider_credential(body: ProviderCredentialIn, org_id: OrgDep, request: Request) -> Envelope[ProviderCredentialOut]:
    """Store a provider API key for every workspace in an organization."""
    return await _create_provider_credential(body, org_id, None, request)


@router.post(
    "/workspaces/{workspace_ref}/provider-credentials",
    tags=["Workspace Provider Credentials"],
    dependencies=[require("api", workspace_scope, Permission.provider_credentials_manage)],
)
async def create_workspace_provider_credential(
    body: ProviderCredentialIn,
    org_id: OrgDep,
    workspace: WorkspaceDep,
    request: Request,
) -> Envelope[ProviderCredentialOut]:
    """Store a provider API key for one workspace."""
    return await _create_provider_credential(body, org_id, workspace, request)


@router.get(
    "/provider-credentials",
    tags=["Organization Provider Credentials"],
    dependencies=[require("api", org_scope, Permission.provider_credentials_read)],
)
async def list_org_provider_credentials(org_id: OrgDep) -> Envelope[list[ProviderCredentialOut]]:
    """List provider credentials owned by an organization, including its workspace credentials."""
    credentials = await ProviderCredential.for_org(org_id)
    return Envelope(data=[ProviderCredentialOut.model_validate(credential) for credential in credentials])


@router.get(
    "/workspaces/{workspace_ref}/provider-credentials",
    tags=["Workspace Provider Credentials"],
    dependencies=[require("api", workspace_scope, Permission.provider_credentials_read)],
)
async def list_workspace_provider_credentials(workspace: WorkspaceDep) -> Envelope[list[ProviderCredentialOut]]:
    """List provider credentials stored specifically for one workspace."""
    credentials = await ProviderCredential.for_org(workspace.org_id, workspace.id)
    return Envelope(data=[ProviderCredentialOut.model_validate(credential) for credential in credentials])


@router.get(
    "/provider-credentials/{credential_id}",
    tags=["Organization Provider Credentials", "Workspace Provider Credentials"],
    dependencies=[require("api", credential_scope, Permission.provider_credentials_read)],
)
async def get_provider_credential(credential: CredentialDep) -> Envelope[ProviderCredentialOut]:
    """Return provider credential metadata without its secret value."""
    return Envelope(data=ProviderCredentialOut.model_validate(credential))


@router.patch(
    "/provider-credentials/{credential_id}",
    tags=["Organization Provider Credentials", "Workspace Provider Credentials"],
    dependencies=[require("api", credential_scope, Permission.provider_credentials_manage)],
)
async def update_provider_credential(body: ProviderCredentialUpdate, credential: CredentialDep) -> Envelope[ProviderCredentialOut]:
    """Update a provider credential's priority or enabled state."""
    return Envelope(data=ProviderCredentialOut.model_validate(await credential.apply(body).save()))


@router.put(
    "/provider-credentials/{credential_id}/value",
    tags=["Organization Provider Credentials", "Workspace Provider Credentials"],
    dependencies=[require("api", credential_scope, Permission.provider_credentials_manage)],
)
async def rotate_provider_credential(body: ProviderCredentialValueIn, credential: CredentialDep, request: Request) -> Envelope[ProviderCredentialOut]:
    """Replace a provider credential's secret value."""
    store = secret_store(request)
    secret = Secret(body.value.get_secret_value())
    credential.fingerprint = await _hold(store, credential, secret)
    credential.version += 1
    credential.status = "unknown"
    return Envelope(data=ProviderCredentialOut.model_validate(await credential.save()))


@router.delete(
    "/provider-credentials/{credential_id}",
    tags=["Organization Provider Credentials", "Workspace Provider Credentials"],
    dependencies=[require("api", credential_scope, Permission.provider_credentials_manage)],
)
async def delete_provider_credential(credential: CredentialDep, request: Request) -> Envelope[DeletedOut[UUID]]:
    """Delete provider credential metadata and its stored secret value."""
    await ProviderCredential.delete_scoped(secret_store(request), ProviderCredential.id == credential.id)
    return Envelope(data=DeletedOut.of(credential.id))
