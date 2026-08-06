from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import col

from control_plane.compiler import UnknownOrgError, compile_and_store
from control_plane.deps import OrgDep  # noqa: TC001 FastAPI resolves dependency annotations at runtime
from control_plane.models import ApiKey, Bundle, DataPlaneInstance, Org, UsageEvent
from control_plane.schemas import Envelope
from control_plane.tokens import mint_inference_key

router = APIRouter(prefix="/org")

# A data plane is considered offline after three missed heartbeats; the row itself is never deleted.
INSTANCE_STALE_AFTER = timedelta(seconds=90)


class KeyIn(BaseModel):
    allowed_models: list[str] = Field(default=["*"], description="Model ids this key may call, * for all")


class KeyOut(BaseModel):
    key_id: str
    token: str


class KeyRevokedOut(BaseModel):
    key_id: str
    status: Literal["revoked"]


class CompileOut(BaseModel):
    bundle_id: str
    version: int


class BundleOut(BaseModel):
    id: UUID
    org_id: str
    version: int
    issued_at: datetime
    expires_at: datetime
    signing_key_id: str


class InstanceOut(BaseModel):
    instance_id: str
    org_id: str | None
    version: str
    bundle_id: UUID | None
    address: str | None
    status: Literal["online", "offline"]
    first_seen: datetime
    last_seen: datetime


@router.post("/keys")
async def create_key(org: OrgDep, body: KeyIn, request: Request) -> Envelope[KeyOut]:
    if await Org.get(org) is None:
        raise HTTPException(status_code=404)
    settings = request.app.state.settings
    key_id, token = await mint_inference_key(org, body.allowed_models, settings.auth.token_signing_key, datetime.now(tz=UTC))
    return Envelope(data=KeyOut(key_id=key_id, token=token))


@router.delete("/keys/{key_id}")
async def revoke_key(org: OrgDep, key_id: str) -> Envelope[KeyRevokedOut]:
    key = await ApiKey.owned_by(org, key_id)
    key.disabled = True
    return Envelope(data=KeyRevokedOut(key_id=key_id, status="revoked"))


@router.post("/bundles/compile")
async def compile_endpoint(org: OrgDep, request: Request) -> Envelope[CompileOut]:
    settings = request.app.state.settings
    now = datetime.now(tz=UTC)
    bundle_id = uuid4()
    try:
        version = await compile_and_store(org, bundle_id, now, settings.bundle.staleness_bound, settings.bundle.signing_key)
    except UnknownOrgError as e:
        raise HTTPException(status_code=404) from e
    return Envelope(data=CompileOut(bundle_id=str(bundle_id), version=version))


@router.get("/keys")
async def list_keys(org: OrgDep) -> Envelope[list[ApiKey]]:
    return Envelope(data=await ApiKey.find(ApiKey.org_id == org, order_by=col(ApiKey.id)))


@router.get("/bundles")
async def list_bundles(org: OrgDep) -> Envelope[list[BundleOut]]:
    rows = await Bundle.find(Bundle.org_id == org, order_by=col(Bundle.version))
    return Envelope(data=[BundleOut(**r.model_dump(exclude={"payload", "signature"})) for r in rows])


@router.get("/instances")
async def list_instances(org: OrgDep, include_offline: bool = False) -> Envelope[list[InstanceOut]]:
    """Data planes serving this org; offline ones are kept as history and shown only with include_offline."""
    now = datetime.now(tz=UTC)
    rows = await DataPlaneInstance.find(DataPlaneInstance.org_id == org, order_by=col(DataPlaneInstance.last_seen).desc())
    out: list[InstanceOut] = []
    for r in rows:
        last_seen = r.last_seen if r.last_seen.tzinfo else r.last_seen.replace(tzinfo=UTC)
        status = "online" if now - last_seen < INSTANCE_STALE_AFTER else "offline"
        if status == "offline" and not include_offline:
            continue
        out.append(InstanceOut(**r.model_dump(), status=status))
    return Envelope(data=out)


@router.get("/events")
async def list_events(org: OrgDep, after: datetime | None = None, limit: int = 50) -> Envelope[list[UsageEvent]]:
    if after is not None:
        conditions = (UsageEvent.org_id == org, col(UsageEvent.occurred_at) > after)
        return Envelope(data=await UsageEvent.find(*conditions, order_by=col(UsageEvent.occurred_at).asc(), limit=limit))
    return Envelope(data=await UsageEvent.find(UsageEvent.org_id == org, order_by=col(UsageEvent.occurred_at).desc(), limit=limit))
