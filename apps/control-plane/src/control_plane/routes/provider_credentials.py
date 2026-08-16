from __future__ import annotations

from typing import Annotated
from uuid import UUID  # noqa: TC003 FastAPI evaluates dependency annotations at runtime

from fastapi import APIRouter, Depends, HTTPException, Request

from contract import Secret, SecretRejectedError, SecretStore
from control_plane.authz import Permission, Target
from control_plane.deps import OrgDep, require
from control_plane.models import Provider, ProviderCredential, Workspace
from control_plane.models.common.wire import DeletedOut, Envelope
from control_plane.models.provider_credential import (
    ProviderCredentialIn,
    ProviderCredentialOut,
    ProviderCredentialUpdate,
    ProviderCredentialValueIn,
)

router = APIRouter(prefix="/org/provider-credentials")


def secret_store(request: Request) -> SecretStore:
    return request.app.state.secret_store


async def _provider(name: str) -> Provider:
    provider = await Provider.first(Provider.name == name)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


async def _workspace_target(org_id: UUID, workspace_ref: str | None) -> Target:
    if workspace_ref is None:
        return Target.org(org_id)
    workspace = await Workspace.by_ref(org_id, workspace_ref)
    return Target.workspace(org_id, workspace.id)


async def create_credential_target(body: ProviderCredentialIn, org_id: OrgDep) -> Target:
    return await _workspace_target(org_id, body.workspace)


async def list_credential_target(org_id: OrgDep, workspace: str | None = None) -> Target:
    return await _workspace_target(org_id, workspace)


async def selected_credential(credential_id: UUID, org_id: OrgDep) -> ProviderCredential:
    return await ProviderCredential.in_org(org_id, credential_id)


CredentialDep = Annotated[ProviderCredential, Depends(selected_credential)]


async def credential_target(credential: CredentialDep) -> Target:
    if credential.workspace_id is not None:
        if credential.org_id is None:
            raise HTTPException(status_code=500, detail="Credential has an invalid boundary")
        return Target.workspace(credential.org_id, credential.workspace_id)
    if credential.org_id is None:
        return Target.instance()
    return Target.org(credential.org_id)


@router.post("", tags=["Provider Credentials"], dependencies=[require(Permission.provider_credentials_manage, create_credential_target)])
async def create_provider_credential(body: ProviderCredentialIn, org_id: OrgDep, request: Request) -> Envelope[ProviderCredentialOut]:
    """Bring a provider key for this org, or for one workspace in it.

    Workspace writes require provider-credential management authority at that workspace: whoever
    supplies the key owns the account its traffic is billed to, and that account's dashboard shows
    every request made with it.

    The row is written before the value so a crash between the two leaves a credential with nothing
    behind it, which the request path already handles by skipping the candidate. The other order
    would leave a value in the store with no row to delete it by.
    """
    store = secret_store(request)
    provider = await _provider(body.provider)
    workspace = await Workspace.by_ref(org_id, body.workspace) if body.workspace else None
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
    """Store the value and report the fingerprint of what the store now holds.

    Taken from what put hands back rather than from the input, because a store that keeps values it
    does not own can accept a put without the result being the argument, and a fingerprint of what
    was sent would then describe a key the request path will never spend.
    """
    try:
        held = await store.put(credential.secret_ref(), secret)
    except SecretRejectedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e
    return held.fingerprint


@router.get("", tags=["Provider Credentials"], dependencies=[require(Permission.provider_credentials_read, list_credential_target)])
async def list_provider_credentials(org_id: OrgDep, workspace: str | None = None) -> Envelope[list[ProviderCredentialOut]]:
    """The org's credentials in the order the data plane tries them, optionally narrowed to one workspace."""
    workspace_id = (await Workspace.by_ref(org_id, workspace)).id if workspace else None
    credentials = await ProviderCredential.for_org(org_id, workspace_id)
    return Envelope(data=[ProviderCredentialOut.model_validate(credential) for credential in credentials])


@router.get("/{credential_id}", tags=["Provider Credentials"], dependencies=[require(Permission.provider_credentials_read, credential_target)])
async def get_provider_credential(credential: CredentialDep) -> Envelope[ProviderCredentialOut]:
    return Envelope(data=ProviderCredentialOut.model_validate(credential))


@router.patch("/{credential_id}", tags=["Provider Credentials"], dependencies=[require(Permission.provider_credentials_manage, credential_target)])
async def update_provider_credential(body: ProviderCredentialUpdate, credential: CredentialDep) -> Envelope[ProviderCredentialOut]:
    """Priority and enabled are the whole mutable surface: everything else names the secret, so
    changing it would orphan the value rather than move it."""
    return Envelope(data=ProviderCredentialOut.model_validate(await credential.apply(body).save()))


@router.put(
    "/{credential_id}/value", tags=["Provider Credentials"], dependencies=[require(Permission.provider_credentials_manage, credential_target)]
)
async def rotate_provider_credential(body: ProviderCredentialValueIn, credential: CredentialDep, request: Request) -> Envelope[ProviderCredentialOut]:
    """A rotation is the same row and the same ref with a new value, so the bundle diff is one
    integer and every data plane refetches within a poll instead of waiting out a cache TTL."""
    store = secret_store(request)
    secret = Secret(body.value.get_secret_value())
    credential.fingerprint = await _hold(store, credential, secret)
    credential.version += 1
    credential.status = "unknown"
    return Envelope(data=ProviderCredentialOut.model_validate(await credential.save()))


@router.delete("/{credential_id}", tags=["Provider Credentials"], dependencies=[require(Permission.provider_credentials_manage, credential_target)])
async def delete_provider_credential(credential: CredentialDep, request: Request) -> Envelope[DeletedOut[UUID]]:
    """Deleting one credential is the same operation a workspace or org delete performs in bulk, so
    it runs through the same method rather than a second copy of the ordering rule."""
    await ProviderCredential.delete_scoped(secret_store(request), ProviderCredential.id == credential.id)
    return Envelope(data=DeletedOut.of(credential.id))
