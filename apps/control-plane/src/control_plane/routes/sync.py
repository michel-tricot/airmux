from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col

from contract import BundleManifest, BundleManifestEntry, BundleV1, HeartbeatV1, UsageStatus
from contract import UsageEvent as UsageEventContract
from contract.budgets import OrgPolicyState, PolicyState, PolicyStateRequest
from control_plane.authority import ensure_allowed_for_scopes
from control_plane.authz import Permission, Scope, ScopeLevel
from control_plane.deps import ActorDep, CredentialScopeDep, SessionDep, credential_scope, require
from control_plane.models import Bundle, DataPlaneInstance, ProviderCredential, UsageEvent
from control_plane.models.budget import budget_states
from control_plane.models.common.wire import Envelope
from control_plane.models.data_plane_instance import HeartbeatOut
from control_plane.models.usage_event import EventsIngestedOut, UsageEventConflictError

if TYPE_CHECKING:
    from control_plane.models.provider_credential import ProviderCredentialStatus

router = APIRouter(tags=["Data Plane API"])

EventBatch = Annotated[list[UsageEventContract], Field(max_length=1000)]

CREDENTIAL_HEALTH: dict[UsageStatus, ProviderCredentialStatus] = {
    "ok": "live",
    "credential_rejected": "invalid",
    "rate_limited": "rate_limited",
}


def _bundle(bundle: Bundle) -> BundleV1:
    return BundleV1.model_validate_json(bundle.payload)


@router.get("/bundles/manifest", dependencies=[require("operational", credential_scope, Permission.bundles_read)])
async def bundle_manifest(scope: CredentialScopeDep) -> Envelope[BundleManifest]:
    """Return every latest organization bundle visible to the authenticated data plane credential."""
    if scope.level is ScopeLevel.workspace:
        raise HTTPException(status_code=403, detail="workspace credentials cannot read organization bundles")
    bundle_refs = await Bundle.latest_refs_per_org(scope.org_id)
    return Envelope(data=BundleManifest(bundles=tuple(BundleManifestEntry(org_id=org_id, bundle_id=bundle_id) for org_id, bundle_id in bundle_refs)))


async def selected_bundle(bundle_id: UUID) -> Bundle:
    bundle = await Bundle.get(bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Bundle not found")
    return bundle


BundleDep = Annotated[Bundle, Depends(selected_bundle)]


async def selected_bundle_scope(bundle: BundleDep) -> Scope:
    return Scope.org(bundle.org_id)


@router.get("/bundles/{bundle_id}", dependencies=[require("operational", selected_bundle_scope, Permission.bundles_read)])
async def get_bundle(bundle: BundleDep) -> Envelope[BundleV1]:
    """Return one immutable bundle visible to the authenticated data plane credential."""
    return Envelope(data=_bundle(bundle))


@router.post("/events", dependencies=[require("operational", credential_scope, Permission.usage_ingest)])
async def ingest_events(actor: ActorDep, scope: CredentialScopeDep, events: EventBatch) -> Envelope[EventsIngestedOut]:
    """Ingest up to 1,000 usage events; repeated events and request attempts are ignored."""
    if not events:
        return Envelope(data=EventsIngestedOut(received=0, ingested=0))
    await ensure_allowed_for_scopes(
        actor,
        Permission.usage_ingest,
        (Scope.workspace(event.org_id, event.workspace_id) for event in events),
    )
    try:
        inserted = await UsageEvent.ingest(events)
    except UsageEventConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    events_by_id = {event.event_id: event for event in events}
    await ProviderCredential.observe(_credential_health([events_by_id[event_id] for event_id in inserted]), org_id=scope.org_id)
    return Envelope(data=EventsIngestedOut(received=len(events), ingested=len(inserted)))


def _credential_health(events: list[UsageEventContract]) -> dict[UUID, tuple[datetime, ProviderCredentialStatus]]:
    health: dict[UUID, tuple[datetime, ProviderCredentialStatus]] = {}
    for event in events:
        status = CREDENTIAL_HEALTH.get(event.status)
        if event.credential_id is None or status is None:
            continue
        seen = health.get(event.credential_id)
        if seen is None or event.occurred_at > seen[0]:
            health[event.credential_id] = (event.occurred_at, status)
    return health


@router.post("/heartbeat", dependencies=[require("operational", credential_scope, Permission.data_planes_heartbeat)])
async def heartbeat(scope: CredentialScopeDep, body: HeartbeatV1, session: SessionDep, request: Request) -> Envelope[HeartbeatOut]:
    """Create or refresh a data-plane instance at the management key's scope."""
    now = datetime.now(tz=UTC)
    address = request.client.host if request.client else None
    fields = {"org_id": scope.org_id, "version": body.version, "bundle_id": body.bundle_id, "address": address, "last_seen": now}
    same_org = col(DataPlaneInstance.org_id).is_(None) if scope.org_id is None else col(DataPlaneInstance.org_id) == scope.org_id
    stmt = (
        pg_insert(DataPlaneInstance)
        .values(instance_id=body.instance_id, first_seen=now, **fields)
        .on_conflict_do_update(index_elements=["instance_id"], set_=fields, where=same_org)
        .returning(col(DataPlaneInstance.instance_id))
    )
    if (await session.execute(stmt)).scalar_one_or_none() is None:
        raise HTTPException(status_code=409, detail="instance_id already belongs to another data-plane scope")
    return Envelope(data=HeartbeatOut(instance_id=body.instance_id))


@router.post("/policy-state/sync", dependencies=[require("operational", credential_scope, Permission.policy_state_sync)])
async def sync_policy_state(actor: ActorDep, body: PolicyStateRequest) -> Envelope[PolicyState]:
    await ensure_allowed_for_scopes(actor, Permission.policy_state_sync, (Scope.org(org_id) for org_id in body.org_ids))
    now = datetime.now(UTC)
    organizations = tuple([OrgPolicyState(org_id=org_id, budgets=await budget_states(org_id, now)) for org_id in body.org_ids])
    return Envelope(data=PolicyState(computed_at=now, organizations=organizations))
