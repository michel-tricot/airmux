from __future__ import annotations

from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException, Request

from contract import Secret, SecretStore
from control_plane.authz import Scope
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


def writable_store(request: Request) -> SecretStore:
    """A store that cannot be written is a deployment choice, not a request failure, so it reads as
    501 rather than as something the caller could fix by trying again."""
    store = secret_store(request)
    if not store.writable:
        detail = f"this instance is configured with the {store.kind} secret store, which cannot hold credentials"
        raise HTTPException(status_code=501, detail=detail)
    return store


async def _provider(name: str) -> Provider:
    provider = await Provider.first(Provider.name == name)
    if provider is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


@router.post("", tags=["Provider Credentials"], dependencies=[require(Scope.provider_credentials_write)])
async def create_provider_credential(body: ProviderCredentialIn, org_id: OrgDep, request: Request) -> Envelope[ProviderCredentialOut]:
    """Bring a provider key for this org, or for one workspace in it.

    The row is written before the value so a crash between the two leaves a credential with nothing
    behind it, which the request path already handles by skipping the candidate. The other order
    would leave a value in the store with no row to delete it by.
    """
    store = writable_store(request)
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
        fingerprint=secret.fingerprint,
    ).save()
    await store.put(credential.secret_ref(), secret)
    return Envelope(data=ProviderCredentialOut.model_validate(credential))


@router.get("", tags=["Provider Credentials"], dependencies=[require(Scope.provider_credentials_read)])
async def list_provider_credentials(org_id: OrgDep, workspace: str | None = None) -> Envelope[list[ProviderCredentialOut]]:
    """The org's credentials in the order the data plane tries them, optionally narrowed to one workspace."""
    workspace_id = (await Workspace.by_ref(org_id, workspace)).id if workspace else None
    credentials = await ProviderCredential.for_org(org_id, workspace_id)
    return Envelope(data=[ProviderCredentialOut.model_validate(credential) for credential in credentials])


@router.get("/{credential_id}", tags=["Provider Credentials"], dependencies=[require(Scope.provider_credentials_read)])
async def get_provider_credential(credential_id: UUID, org_id: OrgDep) -> Envelope[ProviderCredentialOut]:
    return Envelope(data=ProviderCredentialOut.model_validate(await ProviderCredential.in_org(org_id, credential_id)))


@router.patch("/{credential_id}", tags=["Provider Credentials"], dependencies=[require(Scope.provider_credentials_write)])
async def update_provider_credential(credential_id: UUID, body: ProviderCredentialUpdate, org_id: OrgDep) -> Envelope[ProviderCredentialOut]:
    """Priority and enabled are the whole mutable surface: everything else names the secret, so
    changing it would orphan the value rather than move it."""
    credential = await ProviderCredential.in_org(org_id, credential_id)
    return Envelope(data=ProviderCredentialOut.model_validate(await credential.apply(body).save()))


@router.put("/{credential_id}/value", tags=["Provider Credentials"], dependencies=[require(Scope.provider_credentials_write)])
async def rotate_provider_credential(
    credential_id: UUID, body: ProviderCredentialValueIn, org_id: OrgDep, request: Request
) -> Envelope[ProviderCredentialOut]:
    """A rotation is the same row and the same ref with a new value, so the bundle diff is one
    integer and every data plane refetches within a poll instead of waiting out a cache TTL."""
    store = writable_store(request)
    credential = await ProviderCredential.in_org(org_id, credential_id)
    secret = Secret(body.value.get_secret_value())
    await store.put(credential.secret_ref(), secret)
    credential.version += 1
    credential.fingerprint = secret.fingerprint
    credential.status = "unknown"
    return Envelope(data=ProviderCredentialOut.model_validate(await credential.save()))


@router.delete("/{credential_id}", tags=["Provider Credentials"], dependencies=[require(Scope.provider_credentials_write)])
async def delete_provider_credential(credential_id: UUID, org_id: OrgDep, request: Request) -> Envelope[DeletedOut[UUID]]:
    """Deleting one credential is the same operation a workspace or org delete performs in bulk, so
    it runs through the same method rather than a second copy of the ordering rule."""
    credential = await ProviderCredential.in_org(org_id, credential_id)
    await ProviderCredential.delete_scoped(secret_store(request), ProviderCredential.id == credential.id)
    return Envelope(data=DeletedOut.of(credential_id))
