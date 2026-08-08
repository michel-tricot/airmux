from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, HTTPException, Request
from sqlmodel import col

from contract import uuid7
from control_plane.authz import Scope
from control_plane.compiler import UnknownOrgError, compile_and_store
from control_plane.deps import MgmtDep, OrgDep, require
from control_plane.keys import mint_inference_key
from control_plane.models import Bundle, DataPlaneInstance, InferenceKey, Org, UsageEvent
from control_plane.models.bundle import BundleOut
from control_plane.models.common.wire import Envelope
from control_plane.models.data_plane_instance import DataPlaneInstanceOut
from control_plane.models.inference_key import InferenceKeyMintedOut, InferenceKeyOut, InferenceKeyRevokedOut
from control_plane.models.usage_event import UsageEventOut

router = APIRouter(prefix="/org")


@router.post("/keys", tags=["API Keys"], dependencies=[require(Scope.keys_write)])
async def create_key(org_id: OrgDep, claims: MgmtDep) -> Envelope[InferenceKeyMintedOut]:
    if await Org.find_by_id(org_id) is None:
        raise HTTPException(status_code=404)
    key_id, token = await mint_inference_key(org_id, claims.user_id)
    return Envelope(data=InferenceKeyMintedOut(id=key_id, token=token))


@router.delete("/keys/{key_id}", tags=["API Keys"], dependencies=[require(Scope.keys_write)])
async def revoke_key(org_id: OrgDep, key_id: UUID) -> Envelope[InferenceKeyRevokedOut]:
    key = await InferenceKey.owned_by(org_id, key_id)
    key.revoked = True
    return Envelope(data=InferenceKeyRevokedOut(id=key_id, status="revoked"))


@router.post("/bundles/compile", tags=["Bundles"], dependencies=[require(Scope.bundles_write)])
async def compile_endpoint(org_id: OrgDep, request: Request) -> Envelope[BundleOut]:
    settings = request.app.state.settings
    now = datetime.now(tz=UTC)
    try:
        bundle = await compile_and_store(org_id, uuid7(), now, settings.bundle.staleness_bound, settings.bundle.signing_key)
    except UnknownOrgError as e:
        raise HTTPException(status_code=404) from e
    return Envelope(data=BundleOut.model_validate(bundle))


@router.get("/keys", tags=["API Keys"], dependencies=[require(Scope.keys_read)])
async def list_keys(org_id: OrgDep) -> Envelope[list[InferenceKeyOut]]:
    return Envelope(
        data=[InferenceKeyOut.model_validate(r) for r in await InferenceKey.find(InferenceKey.org_id == org_id, order_by=col(InferenceKey.id))]
    )


@router.get("/bundles", tags=["Bundles"], dependencies=[require(Scope.bundles_read)])
async def list_bundles(org_id: OrgDep) -> Envelope[list[BundleOut]]:
    bundles = await Bundle.find(Bundle.org_id == org_id, order_by=col(Bundle.version))
    return Envelope(data=[BundleOut.model_validate(b) for b in bundles])


@router.get("/instances", tags=["Instances"], dependencies=[require(Scope.instances_read)])
async def list_instances(org_id: OrgDep, include_offline: bool = False) -> Envelope[list[DataPlaneInstanceOut]]:
    """Data planes serving this org; offline ones are kept as history and shown only with include_offline."""
    now = datetime.now(tz=UTC)
    instances = await DataPlaneInstance.find(DataPlaneInstance.org_id == org_id, order_by=col(DataPlaneInstance.last_seen).desc())
    out = [DataPlaneInstanceOut(**i.model_dump(), status=status) for i in instances if (status := i.status(now)) == "online" or include_offline]
    return Envelope(data=out)


@router.get("/events", tags=["Events"], dependencies=[require(Scope.events_read)])
async def list_events(org_id: OrgDep, after: datetime | None = None, limit: int = 50) -> Envelope[list[UsageEventOut]]:
    if after is not None:
        conditions = (UsageEvent.org_id == org_id, col(UsageEvent.occurred_at) > after)
        events = await UsageEvent.find(*conditions, order_by=col(UsageEvent.occurred_at).asc(), limit=limit)
    else:
        events = await UsageEvent.find(UsageEvent.org_id == org_id, order_by=col(UsageEvent.occurred_at).desc(), limit=limit)
    return Envelope(data=[UsageEventOut.model_validate(e) for e in events])
