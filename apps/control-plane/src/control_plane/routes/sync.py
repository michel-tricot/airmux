from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID  # noqa: TC003 fastapi resolves query param annotations at runtime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col

from contract import BundleV1, HeartbeatV1, SignedBundle, UsageEventV1
from control_plane.authz import Scope
from control_plane.deps import MgmtDep, SessionDep, require
from control_plane.models import Bundle, DataPlaneInstance, UsageEvent
from control_plane.models.common.wire import Envelope
from control_plane.models.data_plane_instance import HeartbeatOut
from control_plane.models.usage_event import EventsIngestedOut

router = APIRouter(tags=["Sync"])


def _sync_org(claims_org_id: UUID | None, org_id: UUID | None) -> UUID | None:
    """A data plane authenticates with a management token; an org-scoped one is pinned to its org."""
    if claims_org_id is None:
        return org_id
    if org_id is not None and org_id != claims_org_id:
        raise HTTPException(status_code=403)
    return claims_org_id


@router.get("/bundle/latest", dependencies=[require(Scope.sync)])
async def bundle_latest(claims: MgmtDep, org_id: UUID | None = None) -> Envelope[SignedBundle]:
    org_id = _sync_org(claims.org_id, org_id)
    conditions = (Bundle.org_id == org_id,) if org_id else ()
    bundle = await Bundle.first(*conditions, order_by=(col(Bundle.issued_at).desc(), col(Bundle.version).desc()))
    if bundle is None:
        raise HTTPException(status_code=404)
    signed = SignedBundle(payload=BundleV1.model_validate_json(bundle.payload), signature=bundle.signature, signing_key_id=bundle.signing_key_id)
    return Envelope(data=signed)


@router.post("/events", dependencies=[require(Scope.sync)])
async def ingest_events(claims: MgmtDep, events: list[UsageEventV1]) -> Envelope[EventsIngestedOut]:
    """Idempotent upsert on event_id: at-least-once delivery lands exactly once, and a failed batch lands nothing."""
    if claims.org_id is not None and any(event.org_id != claims.org_id for event in events):
        raise HTTPException(status_code=403)
    fresh = [event for event in events if await UsageEvent.get(event.event_id) is None]
    for event in fresh:
        await UsageEvent(**event.model_dump(exclude={"schema_version"})).save()
    return Envelope(data=EventsIngestedOut(received=len(events), ingested=len(fresh)))


@router.post("/heartbeat", dependencies=[require(Scope.sync)])
async def heartbeat(claims: MgmtDep, body: HeartbeatV1, session: SessionDep, request: Request) -> Envelope[HeartbeatOut]:
    """Upsert the instance record; the row persists as history, last_seen drives liveness.

    Every worker of a multi-worker data plane heartbeats with the same instance_id, so the first
    insert can race; do it as one atomic upsert instead of read-then-write.
    """
    org = _sync_org(claims.org_id, body.org_id)
    now = datetime.now(tz=UTC)
    address = request.client.host if request.client else None
    fields = {"org_id": org, "version": body.version, "bundle_id": body.bundle_id, "address": address, "last_seen": now}
    stmt = (
        pg_insert(DataPlaneInstance)
        .values(instance_id=body.instance_id, first_seen=now, **fields)
        .on_conflict_do_update(index_elements=["instance_id"], set_=fields)
    )
    await session.execute(stmt)
    return Envelope(data=HeartbeatOut(instance_id=body.instance_id))
