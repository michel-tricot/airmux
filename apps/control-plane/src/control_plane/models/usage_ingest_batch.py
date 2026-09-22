from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, Column, Identity, func, or_, select, text
from sqlmodel import Field, col

from contract import GatewayRequestFinishedV1, uuid7
from control_plane.db import current_session
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.gateway_request import GatewayRequest
from control_plane.models.usage_event import UsageEvent

if TYPE_CHECKING:
    from contract import IngestEvent
    from contract import UsageEvent as UsageEventContract


INGEST_LOCK = 0x4149524D5558


class IngestConflictError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Ingest event conflicts with existing evidence")


class MissingIngestIdentityError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Usage ingest batch did not receive an identity")


@dataclass(frozen=True)
class IngestResult:
    ingested: int
    inserted_usage_event_ids: tuple[UUID, ...]
    watermark: UUID | None


def _event_fact(event: IngestEvent | UsageEvent) -> dict[str, object]:
    fact = event.model_dump(exclude={"event_id", "event_type", "schema_version", "ingest_id"}, warnings=False)
    if "requested_capabilities" in fact:
        fact["requested_capabilities"] = frozenset(event.requested_capabilities)
    return fact


def _request_fact(event: IngestEvent | GatewayRequest) -> dict[str, object]:
    fields = (
        "request_id",
        "request_started_at",
        "org_id",
        "workspace_id",
        "key_id",
        "authentication_source",
        "authentication_label",
        "user_id",
        "principal_label",
        "principal_type",
        "workspace_label",
        "requested_model_id",
        "requested_capabilities",
        "bundle_id",
        "stream",
    )
    fact = {field: getattr(event, field) for field in fields}
    fact["requested_capabilities"] = frozenset(event.requested_capabilities)
    return fact


def _terminal_fact(event: GatewayRequestFinishedV1 | GatewayRequest) -> dict[str, object]:
    if isinstance(event, GatewayRequestFinishedV1):
        return {
            **_request_fact(event),
            "occurred_at": event.occurred_at,
            "outcome": event.outcome,
            "expected_attempts": event.expected_attempts,
            "latency_ms": event.latency_ms,
        }
    return {
        **_request_fact(event),
        "occurred_at": event.finished_at,
        "outcome": event.outcome,
        "expected_attempts": event.expected_attempts,
        "latency_ms": event.latency_ms,
    }


def _usage_identity(event: UsageEventContract | UsageEvent) -> tuple[UUID, UUID, int | None]:
    return event.org_id, event.request_id, event.attempt_index


class UsageIngestBatch(Record, table=True):
    ingest_id: int | None = Field(default=None, sa_column=Column(BigInteger, Identity(), primary_key=True))
    watermark: UUID = Field(default_factory=uuid7, unique=True)
    received_at: datetime = Field(default=None, sa_type=UTCDateTime, sa_column_kwargs={"server_default": text("clock_timestamp()")})

    @classmethod
    async def ingest(cls, events: list[IngestEvent]) -> IngestResult:
        session = current_session()
        await session.execute(select(func.pg_advisory_xact_lock(INGEST_LOCK)))
        unique_events = _unique_events(events)
        requests = await _requests_for(unique_events)
        usage = await _usage_for(unique_events)
        requests_by_id = {request.request_id: request for request in requests}
        terminal_id_requests = await _terminal_requests_for(unique_events)
        new_events = _new_events(unique_events, requests_by_id, usage, terminal_id_requests)

        _validate_attempt_bounds(unique_events, usage, requests_by_id)
        _validate_request_histories(unique_events, usage, requests_by_id)
        if not new_events:
            return IngestResult(ingested=0, inserted_usage_event_ids=(), watermark=await cls.latest_watermark())

        batch = cls()
        session.add(batch)
        await session.flush()
        if batch.ingest_id is None:
            raise MissingIngestIdentityError
        for event in new_events:
            request = requests_by_id.get(event.request_id)
            if request is None:
                request = _gateway_request(event, batch.ingest_id)
                session.add(request)
                requests_by_id[event.request_id] = request
            if isinstance(event, GatewayRequestFinishedV1):
                request.terminal_event_id = event.event_id
                request.terminal_ingest_id = batch.ingest_id
                request.finished_at = event.occurred_at
                request.outcome = event.outcome
                request.expected_attempts = event.expected_attempts
                request.latency_ms = event.latency_ms
            else:
                session.add(UsageEvent(**event.model_dump(exclude={"event_type", "schema_version"}), ingest_id=batch.ingest_id))
        await session.flush()
        inserted_usage = tuple(event.event_id for event in new_events if not isinstance(event, GatewayRequestFinishedV1))
        return IngestResult(ingested=len(new_events), inserted_usage_event_ids=inserted_usage, watermark=batch.watermark)

    @classmethod
    async def latest_watermark(cls) -> UUID | None:
        return (await current_session().execute(select(col(cls.watermark)).order_by(col(cls.ingest_id).desc()).limit(1))).scalar_one_or_none()


def _unique_events(events: list[IngestEvent]) -> list[IngestEvent]:
    by_event_id: dict[UUID, IngestEvent] = {}
    by_usage_identity: dict[tuple[UUID, UUID, int | None], UsageEventContract] = {}
    by_terminal_request: dict[UUID, GatewayRequestFinishedV1] = {}
    for event in events:
        same_id = by_event_id.get(event.event_id)
        if same_id is not None and (type(same_id) is not type(event) or _event_fact(same_id) != _event_fact(event)):
            raise IngestConflictError
        by_event_id[event.event_id] = event
        if isinstance(event, GatewayRequestFinishedV1):
            terminal = by_terminal_request.get(event.request_id)
            if terminal is not None and _terminal_fact(terminal) != _terminal_fact(event):
                raise IngestConflictError
            by_terminal_request.setdefault(event.request_id, event)
        else:
            identity = _usage_identity(event)
            usage = by_usage_identity.get(identity)
            if usage is not None and _event_fact(usage) != _event_fact(event):
                raise IngestConflictError
            by_usage_identity.setdefault(identity, event)
    unique_ids = set[UUID]()
    unique: list[IngestEvent] = []
    for event in [*by_usage_identity.values(), *by_terminal_request.values()]:
        if event.event_id not in unique_ids:
            unique_ids.add(event.event_id)
            unique.append(event)
    return unique


def _gateway_request(event: IngestEvent, ingest_id: int) -> GatewayRequest:
    return GatewayRequest(
        request_id=event.request_id,
        request_started_at=event.request_started_at,
        org_id=event.org_id,
        workspace_id=event.workspace_id,
        key_id=event.key_id,
        authentication_source=event.authentication_source,
        authentication_label=event.authentication_label,
        user_id=event.user_id,
        principal_label=event.principal_label,
        principal_type=event.principal_type,
        workspace_label=event.workspace_label,
        requested_model_id=event.requested_model_id,
        requested_capabilities=list(event.requested_capabilities),
        bundle_id=event.bundle_id,
        stream=event.stream,
        first_ingest_id=ingest_id,
    )


def _new_events(
    events: list[IngestEvent],
    requests: dict[UUID, GatewayRequest],
    usage: list[UsageEvent],
    terminal_requests: list[GatewayRequest],
) -> list[IngestEvent]:
    usage_by_event_id = {event.event_id: event for event in usage}
    usage_by_identity = {_usage_identity(event): event for event in usage}
    terminal_by_event_id = {request.terminal_event_id: request for request in terminal_requests}
    new_events: list[IngestEvent] = []
    for event in events:
        request = requests.get(event.request_id)
        if request is not None and _request_fact(request) != _request_fact(event):
            raise IngestConflictError
        is_new = (
            _terminal_is_new(event, request, usage_by_event_id, terminal_by_event_id)
            if isinstance(event, GatewayRequestFinishedV1)
            else _usage_is_new(event, usage_by_event_id, usage_by_identity, terminal_by_event_id)
        )
        if is_new:
            new_events.append(event)
    return new_events


def _terminal_is_new(
    event: GatewayRequestFinishedV1,
    request: GatewayRequest | None,
    usage_by_event_id: dict[UUID, UsageEvent],
    terminal_by_event_id: dict[UUID | None, GatewayRequest],
) -> bool:
    if event.event_id in usage_by_event_id:
        raise IngestConflictError
    by_terminal_id = terminal_by_event_id.get(event.event_id)
    if by_terminal_id is not None:
        if _terminal_fact(by_terminal_id) != _terminal_fact(event):
            raise IngestConflictError
        return False
    if request is not None and request.terminal_event_id is not None:
        if _terminal_fact(request) != _terminal_fact(event):
            raise IngestConflictError
        return False
    return True


def _usage_is_new(
    event: UsageEventContract,
    usage_by_event_id: dict[UUID, UsageEvent],
    usage_by_identity: dict[tuple[UUID, UUID, int | None], UsageEvent],
    terminal_by_event_id: dict[UUID | None, GatewayRequest],
) -> bool:
    if event.event_id in terminal_by_event_id:
        raise IngestConflictError
    existing = usage_by_event_id.get(event.event_id) or usage_by_identity.get(_usage_identity(event))
    if existing is None:
        return True
    if _event_fact(existing) != _event_fact(event):
        raise IngestConflictError
    return False


async def _requests_for(events: list[IngestEvent]) -> list[GatewayRequest]:
    request_ids = {event.request_id for event in events}
    return list((await current_session().execute(select(GatewayRequest).where(col(GatewayRequest.request_id).in_(request_ids)))).scalars().all())


async def _usage_for(events: list[IngestEvent]) -> list[UsageEvent]:
    request_ids = {event.request_id for event in events}
    event_ids = {event.event_id for event in events}
    return list(
        (
            await current_session().execute(
                select(UsageEvent).where(or_(col(UsageEvent.request_id).in_(request_ids), col(UsageEvent.event_id).in_(event_ids)))
            )
        )
        .scalars()
        .all()
    )


async def _terminal_requests_for(events: list[IngestEvent]) -> list[GatewayRequest]:
    event_ids = {event.event_id for event in events}
    return list((await current_session().execute(select(GatewayRequest).where(col(GatewayRequest.terminal_event_id).in_(event_ids)))).scalars().all())


def _validate_attempt_bounds(events: list[IngestEvent], stored_usage: list[UsageEvent], requests: dict[UUID, GatewayRequest]) -> None:
    expected = {request_id: request.expected_attempts for request_id, request in requests.items() if request.expected_attempts is not None}
    for event in events:
        if isinstance(event, GatewayRequestFinishedV1):
            existing = expected.get(event.request_id)
            if existing is not None and existing != event.expected_attempts:
                raise IngestConflictError
            expected[event.request_id] = event.expected_attempts
    for event in [*stored_usage, *events]:
        if isinstance(event, GatewayRequestFinishedV1) or event.attempt_index is None:
            continue
        if event.request_id in expected and event.attempt_index > expected[event.request_id]:
            raise IngestConflictError


def _validate_request_histories(
    events: list[IngestEvent],
    stored_usage: list[UsageEvent],
    requests: dict[UUID, GatewayRequest],
) -> None:
    request_ids = {event.request_id for event in events}
    usage_by_request: dict[UUID, dict[tuple[UUID, UUID, int | None], UsageEventContract | UsageEvent]] = {
        request_id: {} for request_id in request_ids
    }
    for event in stored_usage:
        if event.request_id in usage_by_request:
            usage_by_request[event.request_id][_usage_identity(event)] = event
    terminals: dict[UUID, GatewayRequestFinishedV1 | GatewayRequest] = {
        request_id: request for request_id, request in requests.items() if request.terminal_event_id is not None
    }
    for event in events:
        if isinstance(event, GatewayRequestFinishedV1):
            terminals[event.request_id] = event
        else:
            usage_by_request[event.request_id][_usage_identity(event)] = event
    for request_id, usage in usage_by_request.items():
        evidence = list(usage.values())
        denials = [event for event in evidence if event.attempt_index is None]
        routed = [event for event in evidence if event.attempt_index is not None]
        terminal = terminals.get(request_id)
        if terminal is not None:
            terminal_at = terminal.occurred_at if isinstance(terminal, GatewayRequestFinishedV1) else terminal.finished_at
            if terminal_at is None or any(event.occurred_at > terminal_at for event in evidence):
                raise IngestConflictError
            if denials and terminal.outcome != "denied":
                raise IngestConflictError
        if denials and any(event.occurred_at > denials[0].occurred_at for event in routed):
            raise IngestConflictError
