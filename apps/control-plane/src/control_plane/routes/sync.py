from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col

from contract import BundleV1, HeartbeatV1, SignedBundle, UsageEventV1
from control_plane.authz import Boundary, Permission, Target
from control_plane.deps import AuthorityDep, OrgHeader, SessionDep, authorize, require, selected_target
from control_plane.models import Bundle, DataPlaneInstance, Org, ProviderCredential, UsageEvent
from control_plane.models.common.wire import Envelope
from control_plane.models.data_plane_instance import HeartbeatOut
from control_plane.models.usage_event import EventsIngestedOut

router = APIRouter(tags=["Data Plane"])

EventBatch = Annotated[list[UsageEventV1], Field(max_length=1000)]

CREDENTIAL_HEALTH = {"ok": "live", "credential_rejected": "invalid", "rate_limited": "rate_limited"}
"""Usage statuses that say something about the credential; everything else is about the provider."""


async def bundle_target(authority: AuthorityDep, org_id: UUID | None = None, x_org_id: OrgHeader = None) -> Target:
    if authority.boundary in {Boundary.org, Boundary.workspace}:
        if org_id is not None and org_id != authority.org_id:
            raise HTTPException(status_code=403, detail="The credential is bound to a different organization")
        selected = authority.org_id
    else:
        selected = org_id
        if selected is None and x_org_id is not None:
            try:
                selected = UUID(x_org_id)
            except ValueError:
                raise HTTPException(status_code=403, detail="X-Org-Id is not a valid organization id") from None
    if selected is not None and await Org.find_by_id(selected) is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return Target.org(selected) if selected is not None else Target.instance()


BundleTargetDep = Annotated[Target, Depends(bundle_target)]


@router.get("/bundle/latest", dependencies=[require(Permission.bundles_read, bundle_target)])
async def bundle_latest(target: BundleTargetDep) -> Envelope[SignedBundle]:
    conditions = (Bundle.org_id == target.org_id,) if target.org_id is not None else ()
    bundle = await Bundle.first(*conditions, order_by=(col(Bundle.issued_at).desc(), col(Bundle.version).desc()))
    if bundle is None:
        raise HTTPException(status_code=404, detail="No bundle has been compiled yet for this target")
    signed = SignedBundle(payload=BundleV1.model_validate_json(bundle.payload), signature=bundle.signature, signing_key_id=bundle.signing_key_id)
    return Envelope(data=signed)


@router.post("/events", dependencies=[require(Permission.usage_ingest, selected_target)])
async def ingest_events(authority: AuthorityDep, events: EventBatch, session: SessionDep) -> Envelope[EventsIngestedOut]:
    """Idempotent on event_id: at-least-once delivery lands exactly once, and a failed batch lands nothing.

    One atomic upsert rather than a read per event. Reading first would also be racy: two flushes
    carrying the same event_id would both see it missing and collide on the primary key, failing
    both batches, and at-least-once delivery makes that overlap ordinary rather than exotic. The
    outbox drains up to a thousand events at a time, so the per-event round trip cost was real too.
    ingested counts what RETURNING hands back, which under DO NOTHING is exactly the rows written,
    so a replay reports zero.
    """
    if not events:
        return Envelope(data=EventsIngestedOut(received=0, ingested=0))
    for event in events:
        await authorize(authority, Permission.usage_ingest, Target.workspace(event.org_id, event.workspace_id))
    # A batch may repeat an event_id; keep the first so the statement has one row per key
    values = list({event.event_id: event.model_dump(exclude={"schema_version"}) for event in events}.values())
    stmt = pg_insert(UsageEvent).values(values).on_conflict_do_nothing(index_elements=["event_id"]).returning(col(UsageEvent.event_id))
    inserted = (await session.execute(stmt)).scalars().all()
    await ProviderCredential.observe(_credential_health(events), org_id=authority.org_id)
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


@router.post("/heartbeat", dependencies=[require(Permission.data_planes_heartbeat, selected_target)])
async def heartbeat(authority: AuthorityDep, body: HeartbeatV1, session: SessionDep, request: Request) -> Envelope[HeartbeatOut]:
    """Upsert the instance record; the row persists as history, last_seen drives liveness.

    Every worker of a multi-worker data plane heartbeats with the same instance_id, so the first
    insert can race; do it as one atomic upsert instead of read-then-write. The first heartbeat pins
    the id to either the global or organization boundary, and another credential cannot move it.
    """
    now = datetime.now(tz=UTC)
    address = request.client.host if request.client else None
    fields = {"org_id": authority.org_id, "version": body.version, "bundle_id": body.bundle_id, "address": address, "last_seen": now}
    same_org = col(DataPlaneInstance.org_id).is_(None) if authority.org_id is None else col(DataPlaneInstance.org_id) == authority.org_id
    stmt = (
        pg_insert(DataPlaneInstance)
        .values(instance_id=body.instance_id, first_seen=now, **fields)
        .on_conflict_do_update(index_elements=["instance_id"], set_=fields, where=same_org)
        .returning(col(DataPlaneInstance.instance_id))
    )
    if (await session.execute(stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=409, detail="instance_id already belongs to another data-plane boundary")
    return Envelope(data=HeartbeatOut(instance_id=body.instance_id))
