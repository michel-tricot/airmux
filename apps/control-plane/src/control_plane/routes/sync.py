from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import col, select

from contract import BundleV1, HeartbeatV1, SignedBundle, UsageEventV1
from control_plane.deps import SessionDep, require_dp
from control_plane.models import Bundle, DataPlaneInstance, UsageEvent

router = APIRouter(prefix="/v1", dependencies=[Depends(require_dp)])


@router.get("/bundle/latest")
async def bundle_latest(session: SessionDep, org_id: str | None = None) -> SignedBundle:
    query = select(Bundle).order_by(col(Bundle.issued_at).desc(), col(Bundle.version).desc()).limit(1)
    if org_id:
        query = query.where(Bundle.org_id == org_id)
    row = (await session.execute(query)).scalars().first()
    if row is None:
        raise HTTPException(status_code=404)
    return SignedBundle(payload=BundleV1.model_validate_json(row.payload), signature=row.signature, signing_key_id=row.signing_key_id)


@router.post("/events")
async def ingest_events(events: list[UsageEventV1], session: SessionDep) -> dict[str, int]:
    """Idempotent upsert on event_id: at-least-once delivery lands exactly once."""
    ingested = 0
    for event in events:
        if await session.get(UsageEvent, event.event_id) is None:
            session.add(UsageEvent(**event.model_dump(exclude={"schema_version"})))
            ingested += 1
    await session.commit()
    return {"received": len(events), "ingested": ingested}


@router.post("/heartbeat")
async def heartbeat(body: HeartbeatV1, session: SessionDep, request: Request) -> dict[str, str]:
    """Upsert the instance record; the row persists as history, last_seen drives liveness."""
    now = datetime.now(tz=UTC)
    address = request.client.host if request.client else None
    instance = await session.get(DataPlaneInstance, body.instance_id)
    if instance is None:
        instance = DataPlaneInstance(instance_id=body.instance_id, version=body.version, first_seen=now, last_seen=now)
    instance.org_id = body.org_id
    instance.version = body.version
    instance.bundle_id = body.bundle_id
    instance.address = address
    instance.last_seen = now
    session.add(instance)
    await session.commit()
    return {"instance_id": body.instance_id}
