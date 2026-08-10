from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func
from sqlmodel import col, select

from contract import BundleV1, Catalog, CredentialEntry, KeyEntry, ModelEntry, ProviderEntry, canonical_json, sign_bundle
from control_plane.db import current_session
from control_plane.models import Bundle, InferenceKey, Model, Org, Provider, ProviderCredential

if TYPE_CHECKING:
    from datetime import datetime, timedelta
    from uuid import UUID

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SIGNING_KEY_ID = "k1"


class UnknownOrgError(LookupError):
    def __init__(self, org_id: UUID) -> None:
        super().__init__(str(org_id))


async def compile_and_store(org_id: UUID, bundle_id: UUID, now: datetime, staleness_bound: timedelta, signing_key: Ed25519PrivateKey) -> Bundle:
    """Compile, sign, and persist the next bundle version for an org; returns the stored row."""
    bundle = await compile_bundle(org_id, bundle_id, now, staleness_bound)
    signed = sign_bundle(bundle, signing_key, SIGNING_KEY_ID)
    version = (await current_session().execute(select(func.max(Bundle.version)).where(Bundle.org_id == org_id))).scalar() or 0
    return await Bundle(
        id=bundle_id,
        org_id=org_id,
        version=version + 1,
        issued_at=now,
        expires_at=bundle.expires_at,
        payload=canonical_json(bundle),
        signature=signed.signature,
        signing_key_id=signed.signing_key_id,
    ).save()


async def compile_bundle(org_id: UUID, bundle_id: UUID, now: datetime, staleness_bound: timedelta) -> BundleV1:
    """Pure function of database state plus the explicit inputs, so it can be diffed and replayed.

    All nondeterminism (bundle_id, now) is injected by the caller.
    """
    org = await Org.find_by_id(org_id)
    if org is None:
        raise UnknownOrgError(org_id)
    key_rows = await InferenceKey.find(InferenceKey.org_id == org_id, order_by=col(InferenceKey.id))
    provider_rows = await Provider.find(order_by=col(Provider.name))
    model_rows = await Model.find(order_by=col(Model.name))
    provider_names = {p.id: p.name for p in provider_rows}
    credential_order = (col(ProviderCredential.priority), col(ProviderCredential.name))
    credential_rows = await ProviderCredential.find(ProviderCredential.org_id == org_id, order_by=credential_order)
    return BundleV1(
        bundle_id=bundle_id,
        org_id=org_id,
        issued_at=now,
        expires_at=now + staleness_bound,
        keys=[KeyEntry(key_id=str(r.id), org_id=r.org_id, workspace_id=r.workspace_id, token_hash=r.token_hash) for r in key_rows if not r.revoked],
        catalog=Catalog(
            providers=[
                ProviderEntry.model_validate(
                    {
                        "provider_id": r.name,
                        "kind": r.kind,
                        "base_url": r.base_url,
                        "cache_read_multiplier": r.cache_read_multiplier,
                        "cache_write_multiplier": r.cache_write_multiplier,
                    }
                )
                for r in provider_rows
            ],
            credentials=[
                CredentialEntry(ref=r.secret_ref(provider_names[r.provider_id]), priority=r.priority, version=r.version)
                for r in credential_rows
                if r.enabled and r.provider_id in provider_names
            ],
            models=[
                ModelEntry(
                    model_id=r.name,
                    provider_id=provider_names[r.provider_id],
                    upstream_model=r.upstream_model,
                    input_price_per_mtok=r.input_price_per_mtok,
                    output_price_per_mtok=r.output_price_per_mtok,
                    context_window=r.context_window,
                    max_output_tokens=r.max_output_tokens,
                    capabilities=r.capabilities,
                )
                for r in model_rows
            ],
        ),
    )
