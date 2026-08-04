from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import select

from contract import BundleV1, Catalog, KeyEntry, ModelEntry, ProviderEntry
from control_plane.models import ApiKey, Model, Org, Provider

if TYPE_CHECKING:
    from datetime import datetime, timedelta
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class UnknownOrgError(LookupError):
    def __init__(self, org_id: str) -> None:
        super().__init__(org_id)


async def compile_bundle(session: AsyncSession, org_id: str, bundle_id: UUID, now: datetime, staleness_bound: timedelta) -> BundleV1:
    """Pure function of database state plus the explicit inputs, so it can be diffed and replayed.

    All nondeterminism (bundle_id, now) is injected by the caller.
    """
    org = await session.get(Org, org_id)
    if org is None:
        raise UnknownOrgError(org_id)
    key_rows = (await session.execute(select(ApiKey).where(ApiKey.org_id == org_id).order_by(ApiKey.id))).scalars().all()
    provider_rows = (await session.execute(select(Provider).where(Provider.org_id == org_id).order_by(Provider.id))).scalars().all()
    model_rows = (await session.execute(select(Model).where(Model.org_id == org_id).order_by(Model.id))).scalars().all()
    return BundleV1(
        bundle_id=bundle_id,
        org_id=org_id,
        issued_at=now,
        expires_at=now + staleness_bound,
        keys=[KeyEntry(key_id=r.id, org_id=r.org_id, allowed_models=r.allowed_models, disabled=False) for r in key_rows if not r.disabled],
        revocations=[r.id for r in key_rows if r.disabled],
        catalog=Catalog(
            providers=[ProviderEntry(provider_id=r.id, kind=r.kind, base_url=r.base_url, credential_ref=r.credential_ref) for r in provider_rows],
            models=[
                ModelEntry(
                    model_id=r.id,
                    provider_id=r.provider_id,
                    upstream_model=r.upstream_model,
                    input_price_per_mtok=r.input_price_per_mtok,
                    output_price_per_mtok=r.output_price_per_mtok,
                    context_window=r.context_window,
                    capabilities=r.capabilities,
                )
                for r in model_rows
            ],
        ),
    )
