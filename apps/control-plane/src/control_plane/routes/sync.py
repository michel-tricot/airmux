from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID  # noqa: TC003 fastapi resolves query param annotations at runtime

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col

from contract import BundleV1, HeartbeatV1, SignedBundle, UsageEventV1
from control_plane.authz import Scope
from control_plane.deps import MgmtDep, SessionDep, require
from control_plane.models import Bundle, DataPlaneInstance, ProviderCredential, UsageEvent
from control_plane.models.common.wire import Envelope
from control_plane.models.data_plane_instance import HeartbeatOut
from control_plane.models.usage_event import EventsIngestedOut

router = APIRouter(tags=["Data Plane"])

CREDENTIAL_HEALTH = {"ok": "live", "credential_rejected": "invalid", "rate_limited": "rate_limited"}
"""Usage statuses that say something about the credential; everything else is about the provider."""


def _sync_org(claims_org_id: UUID | None, org_id: UUID | None) -> UUID | None:
    """The org a sync request may touch: an instance key leaves the choice to the caller, an
    org-scoped management key pins it. Only the bundle and event paths have an org to pin; the
    heartbeat registers the data plane against the instance and names no org at all."""
    if claims_org_id is None:
        return org_id
    if org_id is not None and org_id != claims_org_id:
        raise HTTPException(status_code=403, detail="This key is scoped to a different org than the one requested")
    return claims_org_id


@router.get("/bundle/latest", dependencies=[require(Scope.sync)])
async def bundle_latest(claims: MgmtDep, org_id: UUID | None = None) -> Envelope[SignedBundle]:
    org_id = _sync_org(claims.org_id, org_id)
    conditions = (Bundle.org_id == org_id,) if org_id else ()
    bundle = await Bundle.first(*conditions, order_by=(col(Bundle.issued_at).desc(), col(Bundle.version).desc()))
    if bundle is None:
        raise HTTPException(status_code=404, detail="No bundle has been compiled yet for this org")
    signed = SignedBundle(payload=BundleV1.model_validate_json(bundle.payload), signature=bundle.signature, signing_key_id=bundle.signing_key_id)
    return Envelope(data=signed)


@router.post("/events", dependencies=[require(Scope.sync)])
async def ingest_events(claims: MgmtDep, events: list[UsageEventV1], session: SessionDep) -> Envelope[EventsIngestedOut]:
    """Idempotent on event_id: at-least-once delivery lands exactly once, and a failed batch lands nothing.

    One atomic upsert rather than a read per event. Reading first would also be racy: two flushes
    carrying the same event_id would both see it missing and collide on the primary key, failing
    both batches, and at-least-once delivery makes that overlap ordinary rather than exotic. The
    outbox drains up to a thousand events at a time, so the per-event round trip cost was real too.
    ingested counts what RETURNING hands back, which under DO NOTHING is exactly the rows written,
    so a replay reports zero.
    """
    if claims.org_id is not None and any(event.org_id != claims.org_id for event in events):
        raise HTTPException(status_code=403, detail="Events may only be ingested for the org this key is scoped to")
    if not events:
        return Envelope(data=EventsIngestedOut(received=0, ingested=0))
    # A batch may repeat an event_id; keep the first so the statement has one row per key
    rows = list({event.event_id: event.model_dump(exclude={"schema_version"}) for event in events}.values())
    stmt = pg_insert(UsageEvent).values(rows).on_conflict_do_nothing(index_elements=["event_id"]).returning(col(UsageEvent.event_id))
    inserted = (await session.execute(stmt)).scalars().all()
    await ProviderCredential.observe(_credential_health(events))
    return Envelope(data=EventsIngestedOut(received=len(events), ingested=len(inserted)))


def _credential_health(events: list[UsageEventV1]) -> dict[UUID, tuple[datetime, str]]:
    """The newest thing each credential's events say about it.

    Only the outcomes that are facts about the key are worth recording: a provider outage says
    nothing about whether the key is good. A replay carries old events, so the batch is reduced by
    occurred_at rather than by arrival order.
    """
    health: dict[UUID, tuple[datetime, str]] = {}
    for event in events:
        status = CREDENTIAL_HEALTH.get(event.status)
        if event.credential_id is None or status is None:
            continue
        seen = health.get(event.credential_id)
        if seen is None or event.occurred_at > seen[0]:
            health[event.credential_id] = (event.occurred_at, status)
    return health


@router.post("/heartbeat", dependencies=[require(Scope.sync)])
async def heartbeat(_claims: MgmtDep, body: HeartbeatV1, session: SessionDep, request: Request) -> Envelope[HeartbeatOut]:
    """Upsert the instance record; the row persists as history, last_seen drives liveness.

    Every worker of a multi-worker data plane heartbeats with the same instance_id, so the first
    insert can race; do it as one atomic upsert instead of read-then-write.
    """
    now = datetime.now(tz=UTC)
    address = request.client.host if request.client else None
    fields = {"version": body.version, "bundle_id": body.bundle_id, "address": address, "last_seen": now}
    stmt = (
        pg_insert(DataPlaneInstance)
        .values(instance_id=body.instance_id, first_seen=now, **fields)
        .on_conflict_do_update(index_elements=["instance_id"], set_=fields)
    )
    await session.execute(stmt)
    return Envelope(data=HeartbeatOut(instance_id=body.instance_id))
