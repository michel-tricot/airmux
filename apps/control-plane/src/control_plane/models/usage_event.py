from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Column, Index, Numeric, String, func
from sqlalchemy import select as sql_select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, col, select

from contract import CredentialScope, RequestSource, TokenUsageSource, UsageStatus, UsdAmount
from contract.model_types import RequestCapability
from contract.money import ZERO_USD
from control_plane.db import current_session
from control_plane.models.common import PageQuery, PageSlice, keyset_page
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut


class UsageEvent(Record, table=True):
    __table_args__: ClassVar = (
        Index("usage_event_org_occurred_event_idx", "org_id", "occurred_at", "event_id"),
        Index("usage_event_org_workspace_occurred_event_idx", "org_id", "workspace_id", "occurred_at", "event_id"),
        Index("usage_event_org_event_idx", "org_id", "event_id"),
        Index("usage_event_org_workspace_event_idx", "org_id", "workspace_id", "event_id"),
        Index("usage_event_org_request_idx", "org_id", "request_id"),
        Index("usage_event_org_request_started_idx", "org_id", "request_started_at"),
        Index("usage_event_org_workspace_request_started_idx", "org_id", "workspace_id", "request_started_at"),
    )

    event_id: UUID = Field(primary_key=True)
    request_id: UUID
    request_started_at: datetime = Field(sa_type=UTCDateTime)
    attempt_started_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    occurred_at: datetime = Field(sa_type=UTCDateTime)
    org_id: UUID
    workspace_id: UUID
    key_id: str
    request_source: RequestSource = Field(sa_type=String)
    user_id: UUID
    requested_model_id: str
    requested_capabilities: list[RequestCapability] = Field(sa_column=Column(ARRAY(String), nullable=False))
    model_id: str
    provider_id: str
    bundle_id: UUID
    input_tokens: int
    output_tokens: int
    token_usage_source: TokenUsageSource = Field(sa_type=String)
    max_output_tokens: int | None = None
    cost_usd: UsdAmount = Field(sa_column=Column(Numeric(28, 12), nullable=False))
    cost_input_usd: UsdAmount = Field(default=ZERO_USD, sa_column=Column(Numeric(28, 12), nullable=False))
    cost_output_usd: UsdAmount = Field(default=ZERO_USD, sa_column=Column(Numeric(28, 12), nullable=False))
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int
    status: UsageStatus = Field(sa_type=String)
    stream: bool
    credential_id: UUID | None = None
    credential_scope: CredentialScope | None = Field(default=None, sa_type=String)

    @classmethod
    async def usage_report(cls, org_id: UUID, workspace_id: UUID | None, days: int) -> UsageReportOut:
        since = datetime.now(UTC) - timedelta(days=days)
        filters = [col(cls.org_id) == org_id, col(cls.request_started_at) >= since]
        if workspace_id is not None:
            filters.append(col(cls.workspace_id) == workspace_id)
        totals_stmt = sql_select(
            func.count(func.distinct(col(cls.request_id))),
            func.coalesce(func.sum(col(cls.input_tokens)), 0),
            func.coalesce(func.sum(col(cls.output_tokens)), 0),
            func.coalesce(func.sum(col(cls.cost_usd)), ZERO_USD),
        ).where(*filters)
        total_values = (await current_session().execute(totals_stmt)).one()
        day = func.date_trunc("day", col(cls.request_started_at)).label("date")
        daily_stmt = (
            sql_select(
                day,
                func.count(func.distinct(col(cls.request_id))),
                func.coalesce(func.sum(col(cls.input_tokens)), 0),
                func.coalesce(func.sum(col(cls.output_tokens)), 0),
                func.coalesce(func.sum(col(cls.cost_usd)), ZERO_USD),
            )
            .where(*filters)
            .group_by("date")
            .order_by("date")
        )
        daily = (await current_session().execute(daily_stmt)).all()
        models_stmt = (
            sql_select(
                col(cls.model_id),
                func.count(func.distinct(col(cls.request_id))),
                func.coalesce(func.sum(col(cls.input_tokens)), 0),
                func.coalesce(func.sum(col(cls.output_tokens)), 0),
                func.coalesce(func.sum(col(cls.cost_usd)), ZERO_USD),
            )
            .where(*filters)
            .group_by(col(cls.model_id))
            .order_by(func.sum(col(cls.cost_usd)).desc())
        )
        models = (await current_session().execute(models_stmt)).all()
        return UsageReportOut(
            totals=UsageTotalsOut(requests=total_values[0], input_tokens=total_values[1], output_tokens=total_values[2], cost_usd=total_values[3]),
            daily=[
                UsageDayOut(date=values[0], requests=values[1], input_tokens=values[2], output_tokens=values[3], cost_usd=values[4])
                for values in daily
            ],
            models=[
                UsageBreakdownOut(name=values[0], requests=values[1], input_tokens=values[2], output_tokens=values[3], cost_usd=values[4])
                for values in models
            ],
        )

    @classmethod
    async def requests(cls, org_id: UUID, workspace_id: UUID | None, query: UsageRequestQuery) -> RequestPageOut:
        since = datetime.now(UTC) - timedelta(days=query.days)
        filters = [col(cls.org_id) == org_id, col(cls.request_started_at) >= since]
        if workspace_id is not None:
            filters.append(col(cls.workspace_id) == workspace_id)
        started = func.max(col(cls.request_started_at))
        groups_stmt = (
            sql_select(col(cls.request_id), started)
            .where(*filters)
            .group_by(col(cls.request_id))
            .order_by(started.desc(), col(cls.request_id).desc())
            .offset(query.offset)
            .limit(query.limit + 1)
        )
        groups = (await current_session().execute(groups_stmt)).all()
        visible = groups[: query.limit]
        if not visible:
            return RequestPageOut(requests=[], next_offset=None)
        request_ids = [group[0] for group in visible]
        events_stmt = (
            select(cls)
            .where(col(cls.org_id) == org_id, col(cls.request_id).in_(request_ids))
            .order_by(col(cls.request_id), col(cls.attempt_started_at), col(cls.occurred_at), col(cls.event_id))
        )
        if workspace_id is not None:
            events_stmt = events_stmt.where(col(cls.workspace_id) == workspace_id)
        events = (await current_session().execute(events_stmt)).scalars().all()
        grouped: dict[UUID, list[UsageEvent]] = {}
        for event in events:
            grouped.setdefault(event.request_id, []).append(event)
        requests = [_request_out(grouped[request_id]) for request_id in request_ids]
        return RequestPageOut(requests=requests, next_offset=query.offset + query.limit if len(groups) > query.limit else None)

    @classmethod
    async def for_scope(
        cls,
        org_id: UUID,
        workspace_id: UUID | None,
        page: PageQuery,
    ) -> PageSlice[Self]:
        statement = select(cls).where(cls.org_id == org_id)
        if workspace_id is not None:
            statement = statement.where(cls.workspace_id == workspace_id)
        return await keyset_page(statement, page, col(cls.event_id), UUID)


class UsageEventOut(RecordOut[UsageEvent]):
    event_id: UUID
    request_id: UUID
    request_started_at: datetime
    attempt_started_at: datetime | None
    occurred_at: datetime
    org_id: UUID
    workspace_id: UUID
    key_id: str
    request_source: RequestSource
    user_id: UUID
    requested_model_id: str
    requested_capabilities: list[RequestCapability]
    model_id: str
    provider_id: str
    bundle_id: UUID
    input_tokens: int
    output_tokens: int
    token_usage_source: TokenUsageSource = Field(
        description="Token-count provenance: provider, estimated (including partial provider counts), or not_applicable for denials; "
        "independent of cost estimates"
    )
    max_output_tokens: int | None
    cost_usd: UsdAmount
    cost_input_usd: UsdAmount
    cost_output_usd: UsdAmount
    cache_read_tokens: int
    cache_write_tokens: int
    latency_ms: int
    status: UsageStatus
    stream: bool
    credential_id: UUID | None
    credential_scope: CredentialScope | None


class UsageTotalsOut(BaseModel):
    requests: int
    input_tokens: int
    output_tokens: int
    cost_usd: UsdAmount


class UsageBreakdownOut(BaseModel):
    name: str
    requests: int
    input_tokens: int
    output_tokens: int
    cost_usd: UsdAmount


class UsageDayOut(BaseModel):
    date: datetime
    requests: int
    input_tokens: int
    output_tokens: int
    cost_usd: UsdAmount


class UsageReportOut(BaseModel):
    totals: UsageTotalsOut
    daily: list[UsageDayOut]
    models: list[UsageBreakdownOut]


class RequestAttemptOut(BaseModel):
    event_id: UUID
    provider_id: str
    model_id: str
    status: UsageStatus
    input_tokens: int
    output_tokens: int
    cost_usd: UsdAmount
    latency_ms: int


class RequestOut(BaseModel):
    request_id: UUID
    started_at: datetime
    status: UsageStatus
    model_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: UsdAmount
    attempts: list[RequestAttemptOut]


class RequestPageOut(BaseModel):
    requests: list[RequestOut]
    next_offset: int | None


class UsageRequestQuery(BaseModel):
    days: int = Field(default=30, ge=1, le=90)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class UsageReportQuery(BaseModel):
    days: int = Field(default=30, ge=1, le=90)


def _request_out(events: list[UsageEvent]) -> RequestOut:
    latest = max(events, key=lambda event: (event.attempt_started_at or event.request_started_at, event.occurred_at, event.event_id))
    return RequestOut(
        request_id=latest.request_id,
        started_at=latest.request_started_at,
        status=latest.status,
        model_id=latest.model_id,
        input_tokens=sum(event.input_tokens for event in events),
        output_tokens=sum(event.output_tokens for event in events),
        cost_usd=sum((event.cost_usd for event in events), ZERO_USD),
        attempts=[
            RequestAttemptOut(
                event_id=event.event_id,
                provider_id=event.provider_id,
                model_id=event.model_id,
                status=event.status,
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
                cost_usd=event.cost_usd,
                latency_ms=event.latency_ms,
            )
            for event in events
        ],
    )


class EventsIngestedOut(BaseModel):
    received: int
    ingested: int
    rejected: int
