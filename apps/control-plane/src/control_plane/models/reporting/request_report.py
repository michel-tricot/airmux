from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy import select as sql_select
from sqlmodel import col

from contract import RequestSource, TokenUsageSource, UsageStatus, UsdAmount
from contract.money import ZERO_USD
from control_plane.db import current_session
from control_plane.models.reporting.names import names_for_dimension
from control_plane.models.usage_event import UsageEvent

if TYPE_CHECKING:
    from sqlalchemy.sql import Select

    from control_plane.models.reporting.query import ReportQuery, RequestQuery


class RequestSummaryOut(BaseModel):
    request_id: UUID
    started_at: datetime
    status: UsageStatus
    workspace_id: UUID
    workspace_name: str
    key_id: str
    key_name: str
    request_source: RequestSource
    user_id: UUID
    user_email: str
    requested_model_id: str
    model_id: str
    provider_id: str
    attempt_count: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: UsdAmount


class RequestAttemptOut(BaseModel):
    event_id: UUID
    attempt_started_at: datetime | None
    occurred_at: datetime
    provider_id: str
    model_id: str
    credential_id: UUID | None
    credential_name: str | None
    status: UsageStatus
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: UsdAmount
    cost_input_usd: UsdAmount
    cost_output_usd: UsdAmount
    token_usage_source: TokenUsageSource
    latency_ms: int
    matches_filter: bool


class RequestDetailOut(RequestSummaryOut):
    within_period: bool
    attempts: list[RequestAttemptOut]

    @classmethod
    async def for_scope(cls, org_id: UUID, request_id: UUID, query: ReportQuery, now: datetime) -> RequestDetailOut | None:
        conditions = [col(UsageEvent.org_id) == org_id, col(UsageEvent.request_id) == request_id]
        if query.workspace_id is not None:
            conditions.append(col(UsageEvent.workspace_id) == query.workspace_id)
        events = await UsageEvent.find(*conditions)
        if not events:
            return None
        events.sort(key=lambda event: (event.attempt_started_at or event.request_started_at, event.occurred_at, event.event_id))
        latest = events[-1]
        window = query.window(now)
        workspace_names = await names_for_dimension(org_id, query.workspace_id, "workspace", [str(latest.workspace_id)])
        key_names = await names_for_dimension(org_id, query.workspace_id, "key", [latest.key_id])
        user_names = await names_for_dimension(org_id, query.workspace_id, "owner", [str(latest.user_id)])
        credential_names = await names_for_dimension(
            org_id, query.workspace_id, "credential", [str(event.credential_id) for event in events if event.credential_id is not None]
        )
        attempts = [
            RequestAttemptOut(
                event_id=event.event_id,
                attempt_started_at=event.attempt_started_at,
                occurred_at=event.occurred_at,
                provider_id=event.provider_id,
                model_id=event.model_id,
                credential_id=event.credential_id,
                credential_name=credential_names.get(str(event.credential_id), str(event.credential_id)) if event.credential_id else None,
                status=event.status,
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
                cache_read_tokens=event.cache_read_tokens,
                cache_write_tokens=event.cache_write_tokens,
                cost_usd=event.cost_usd,
                cost_input_usd=event.cost_input_usd,
                cost_output_usd=event.cost_output_usd,
                token_usage_source=event.token_usage_source,
                latency_ms=event.latency_ms,
                matches_filter=_matches(event, query),
            )
            for event in events
        ]
        return cls(
            request_id=request_id,
            started_at=latest.request_started_at,
            status=latest.status,
            workspace_id=latest.workspace_id,
            workspace_name=workspace_names.get(str(latest.workspace_id), str(latest.workspace_id)),
            key_id=latest.key_id,
            key_name="Playground" if latest.request_source == "playground" else key_names.get(latest.key_id, latest.key_id),
            request_source=latest.request_source,
            user_id=latest.user_id,
            user_email=user_names.get(str(latest.user_id), str(latest.user_id)),
            requested_model_id=latest.requested_model_id,
            model_id=latest.model_id,
            provider_id=latest.provider_id,
            attempt_count=sum(event.status != "denied" for event in events),
            input_tokens=sum(event.input_tokens for event in events),
            output_tokens=sum(event.output_tokens for event in events),
            cache_read_tokens=sum(event.cache_read_tokens for event in events),
            cache_write_tokens=sum(event.cache_write_tokens for event in events),
            cost_usd=sum((event.cost_usd for event in events), ZERO_USD),
            within_period=window.start_at <= latest.request_started_at < window.end_at,
            attempts=attempts,
        )


class RequestPageOut(BaseModel):
    requests: list[RequestSummaryOut]
    next_offset: int | None

    @classmethod
    async def for_scope(cls, org_id: UUID, query: RequestQuery, now: datetime) -> RequestPageOut:
        statement = _request_statement(org_id, query, now).offset(query.offset).limit(query.limit + 1)
        requests = (await current_session().execute(statement)).mappings().all()
        page = requests[: query.limit]
        workspace_names = await names_for_dimension(org_id, query.workspace_id, "workspace", [str(request["workspace_id"]) for request in page])
        key_names = await names_for_dimension(org_id, query.workspace_id, "key", [request["key_id"] for request in page])
        user_names = await names_for_dimension(org_id, query.workspace_id, "owner", [str(request["user_id"]) for request in page])
        return cls(
            requests=[
                RequestSummaryOut.model_validate(
                    {
                        **request,
                        "workspace_name": workspace_names.get(str(request["workspace_id"]), str(request["workspace_id"])),
                        "key_name": "Playground"
                        if request["request_source"] == "playground"
                        else key_names.get(request["key_id"], request["key_id"]),
                        "user_email": user_names.get(str(request["user_id"]), str(request["user_id"])),
                    }
                )
                for request in page
            ],
            next_offset=query.offset + query.limit if len(requests) > query.limit else None,
        )


class RequestExportOut(BaseModel):
    filename: str
    csv: str

    @classmethod
    async def for_scope(cls, org_id: UUID, query: RequestQuery, now: datetime) -> RequestExportOut:
        requests = (await current_session().execute(_request_statement(org_id, query, now))).mappings().all()
        output = StringIO()
        writer = csv.writer(output)
        fields = (
            "request_id",
            "started_at",
            "status",
            "workspace_id",
            "key_id",
            "request_source",
            "user_id",
            "requested_model_id",
            "model_id",
            "provider_id",
            "attempt_count",
            "input_tokens",
            "output_tokens",
            "cost_usd",
        )
        writer.writerow(fields)
        for request in requests:
            writer.writerow([_csv_value(request[field]) for field in fields])
        return cls(filename=f"airmux-requests-{now.date().isoformat()}.csv", csv=output.getvalue())


def _csv_value(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _request_statement(org_id: UUID, query: RequestQuery, now: datetime) -> Select:
    window = query.window(now)
    conditions = query.conditions(org_id, None if query.request_id is not None else window)
    if query.request_id is not None:
        conditions.append(col(UsageEvent.request_id) == query.request_id)
    matching = (
        sql_select(
            col(UsageEvent.request_id).label("request_id"),
            func.min(col(UsageEvent.request_started_at)).label("started_at"),
            func.sum(col(UsageEvent.input_tokens)).label("input_tokens"),
            func.sum(col(UsageEvent.output_tokens)).label("output_tokens"),
            func.sum(col(UsageEvent.cache_read_tokens)).label("cache_read_tokens"),
            func.sum(col(UsageEvent.cache_write_tokens)).label("cache_write_tokens"),
            func.sum(col(UsageEvent.cost_usd)).label("cost_usd"),
        )
        .where(*conditions)
        .group_by(col(UsageEvent.request_id))
        .subquery()
    )
    full_scope = [col(UsageEvent.org_id) == org_id, col(UsageEvent.request_id).in_(sql_select(matching.c.request_id))]
    if query.workspace_id is not None:
        full_scope.append(col(UsageEvent.workspace_id) == query.workspace_id)
    latest = (
        sql_select(
            col(UsageEvent.request_id).label("request_id"),
            col(UsageEvent.status).label("status"),
            col(UsageEvent.workspace_id).label("workspace_id"),
            col(UsageEvent.key_id).label("key_id"),
            col(UsageEvent.request_source).label("request_source"),
            col(UsageEvent.user_id).label("user_id"),
            col(UsageEvent.requested_model_id).label("requested_model_id"),
            col(UsageEvent.model_id).label("model_id"),
            col(UsageEvent.provider_id).label("provider_id"),
            func.row_number()
            .over(
                partition_by=col(UsageEvent.request_id),
                order_by=(
                    func.coalesce(col(UsageEvent.attempt_started_at), col(UsageEvent.request_started_at)).desc(),
                    col(UsageEvent.occurred_at).desc(),
                    col(UsageEvent.event_id).desc(),
                ),
            )
            .label("position"),
        )
        .where(*full_scope)
        .subquery()
    )
    attempts = (
        sql_select(
            col(UsageEvent.request_id).label("request_id"),
            func.sum(case((col(UsageEvent.status) != "denied", 1), else_=0)).label("attempt_count"),
        )
        .where(*full_scope)
        .group_by(col(UsageEvent.request_id))
        .subquery()
    )
    statement = (
        sql_select(
            matching.c.request_id,
            matching.c.started_at,
            latest.c.status,
            latest.c.workspace_id,
            latest.c.key_id,
            latest.c.request_source,
            latest.c.user_id,
            latest.c.requested_model_id,
            latest.c.model_id,
            latest.c.provider_id,
            attempts.c.attempt_count,
            matching.c.input_tokens,
            matching.c.output_tokens,
            matching.c.cache_read_tokens,
            matching.c.cache_write_tokens,
            matching.c.cost_usd,
        )
        .join(latest, (latest.c.request_id == matching.c.request_id) & (latest.c.position == 1))
        .join(attempts, attempts.c.request_id == matching.c.request_id)
    )
    if query.status is not None and query.request_id is None:
        statement = statement.where(latest.c.status == query.status)
    if query.multiple_attempts and query.request_id is None:
        statement = statement.where(attempts.c.attempt_count > 1)
    return (
        statement.order_by(matching.c.cost_usd.desc(), matching.c.started_at.desc(), matching.c.request_id.desc())
        if query.sort_by == "cost"
        else statement.order_by(matching.c.started_at.desc(), matching.c.request_id.desc())
    )


def _matches(event: UsageEvent, query: ReportQuery) -> bool:
    return (
        (query.owner_id is None or event.user_id == query.owner_id)
        and (query.key_id is None or event.key_id == query.key_id)
        and (query.model_id is None or event.model_id == query.model_id)
        and (query.provider_id is None or event.provider_id == query.provider_id)
        and (query.credential_id is None or event.credential_id == query.credential_id)
    )
