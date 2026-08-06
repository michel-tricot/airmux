from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import col

from control_plane.compiler import UnknownOrgError, compile_and_store
from control_plane.deps import MgmtDep, OrgDep  # noqa: TC001 FastAPI resolves dependency annotations at runtime
from control_plane.models import ApiKey, Bundle, DataPlaneInstance, Org, UsageEvent
from control_plane.models.api_key import ApiKeyOut, KeyOut, KeyRevokedOut
from control_plane.models.bundle import BundleOut, CompileOut
from control_plane.models.data_plane_instance import DataPlaneInstanceOut
from control_plane.models.usage_event import UsageEventOut
from control_plane.schemas import Envelope
from control_plane.tokens import mint_inference_key

router = APIRouter(prefix="/org")


@router.post("/keys", tags=["API Keys"])
async def create_key(org: OrgDep, claims: MgmtDep) -> Envelope[KeyOut]:
    if await Org.get(org) is None:
        raise HTTPException(status_code=404)
    key_id, token = await mint_inference_key(org, claims.user_id)
    return Envelope(data=KeyOut(key_id=key_id, token=token))


@router.delete("/keys/{key_id}", tags=["API Keys"])
async def revoke_key(org: OrgDep, key_id: str) -> Envelope[KeyRevokedOut]:
    key = await ApiKey.owned_by(org, key_id)
    key.disabled = True
    return Envelope(data=KeyRevokedOut(key_id=key_id, status="revoked"))


@router.post("/bundles/compile", tags=["Bundles"])
async def compile_endpoint(org: OrgDep, request: Request) -> Envelope[CompileOut]:
    settings = request.app.state.settings
    now = datetime.now(tz=UTC)
    bundle_id = uuid4()
    try:
        version = await compile_and_store(org, bundle_id, now, settings.bundle.staleness_bound, settings.bundle.signing_key)
    except UnknownOrgError as e:
        raise HTTPException(status_code=404) from e
    return Envelope(data=CompileOut(bundle_id=str(bundle_id), version=version))


@router.get("/keys", tags=["API Keys"])
async def list_keys(org: OrgDep) -> Envelope[list[ApiKeyOut]]:
    return Envelope(data=[ApiKeyOut.model_validate(r) for r in await ApiKey.find(ApiKey.org_id == org, order_by=col(ApiKey.id))])


@router.get("/bundles", tags=["Bundles"])
async def list_bundles(org: OrgDep) -> Envelope[list[BundleOut]]:
    rows = await Bundle.find(Bundle.org_id == org, order_by=col(Bundle.version))
    return Envelope(data=[BundleOut.model_validate(r) for r in rows])


@router.get("/instances", tags=["Instances"])
async def list_instances(org: OrgDep, include_offline: bool = False) -> Envelope[list[DataPlaneInstanceOut]]:
    """Data planes serving this org; offline ones are kept as history and shown only with include_offline."""
    now = datetime.now(tz=UTC)
    rows = await DataPlaneInstance.find(DataPlaneInstance.org_id == org, order_by=col(DataPlaneInstance.last_seen).desc())
    out = [DataPlaneInstanceOut(**r.model_dump(), status=status) for r in rows if (status := r.status(now)) == "online" or include_offline]
    return Envelope(data=out)


@router.get("/events", tags=["Events"])
async def list_events(org: OrgDep, after: datetime | None = None, limit: int = 50) -> Envelope[list[UsageEventOut]]:
    if after is not None:
        conditions = (UsageEvent.org_id == org, col(UsageEvent.occurred_at) > after)
        rows = await UsageEvent.find(*conditions, order_by=col(UsageEvent.occurred_at).asc(), limit=limit)
    else:
        rows = await UsageEvent.find(UsageEvent.org_id == org, order_by=col(UsageEvent.occurred_at).desc(), limit=limit)
    return Envelope(data=[UsageEventOut.model_validate(r) for r in rows])
