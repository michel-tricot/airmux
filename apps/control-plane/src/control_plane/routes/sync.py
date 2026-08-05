from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import col

from contract import BundleV1, HeartbeatV1, SignedBundle, UsageEventV1
from control_plane.deps import MgmtDep, SessionDep  # noqa: TC001 FastAPI resolves dependency annotations at runtime
from control_plane.models import Bundle, DataPlaneInstance, UsageEvent

router = APIRouter(prefix="/v1")


def _sync_org(claims_org: str | None, org_id: str | None) -> str | None:
    """A data plane authenticates with a management token; an org-scoped one is pinned to its org."""
    if claims_org is None:
        return org_id
    if org_id is not None and org_id != claims_org:
        raise HTTPException(status_code=403)
    return claims_org


@router.get("/bundle/latest")
async def bundle_latest(claims: MgmtDep, org_id: str | None = None) -> SignedBundle:
    org = _sync_org(claims.org_id, org_id)
    conditions = (Bundle.org_id == org,) if org else ()
    row = await Bundle.first(*conditions, order_by=(col(Bundle.issued_at).desc(), col(Bundle.version).desc()))
    if row is None:
        raise HTTPException(status_code=404)
    return SignedBundle(payload=BundleV1.model_validate_json(row.payload), signature=row.signature, signing_key_id=row.signing_key_id)


@router.post("/events")
async def ingest_events(claims: MgmtDep, events: list[UsageEventV1]) -> dict[str, int]:
    """Idempotent upsert on event_id: at-least-once delivery lands exactly once, and a failed batch lands nothing."""
    if claims.org_id is not None and any(event.org_id != claims.org_id for event in events):
        raise HTTPException(status_code=403)
    fresh = [event for event in events if await UsageEvent.get(event.event_id) is None]
    for event in fresh:
        await UsageEvent(**event.model_dump(exclude={"schema_version"})).save()
    return {"received": len(events), "ingested": len(fresh)}


@router.post("/heartbeat")
async def heartbeat(claims: MgmtDep, body: HeartbeatV1, session: SessionDep, request: Request) -> dict[str, str]:
    """Upsert the instance record; the row persists as history, last_seen drives liveness.

    Every worker of a multi-worker data plane heartbeats with the same instance_id, so the first
    insert can race; do it as one atomic upsert instead of read-then-write.
    """
    org = _sync_org(claims.org_id, body.org_id)
    now = datetime.now(tz=UTC)
    address = request.client.host if request.client else None
    fields = {"org_id": org, "version": body.version, "bundle_id": body.bundle_id, "address": address, "last_seen": now}
    stmt = (
        sqlite_insert(DataPlaneInstance)
        .values(instance_id=body.instance_id, first_seen=now, **fields)
        .on_conflict_do_update(index_elements=[DataPlaneInstance.instance_id], set_=fields)
    )
    await session.execute(stmt)
    return {"instance_id": body.instance_id}
