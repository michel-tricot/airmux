from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy import select as sql_select
from sqlmodel import col

from contract import UsdAmount
from contract.money import ZERO_USD
from control_plane.db import current_session
from control_plane.models.reporting.query import ReportQuery, ReportWindow
from control_plane.models.usage_event import UsageEvent

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy import ColumnElement


class UsageTotalsOut(BaseModel):
    requests: int
    input_tokens: int
    output_tokens: int
    cost_usd: UsdAmount


class UsageDayOut(UsageTotalsOut):
    date: datetime


class UsageReportOut(BaseModel):
    totals: UsageTotalsOut
    comparison: UsageTotalsOut
    daily: list[UsageDayOut]
    period: ReportWindow
    updated_at: datetime

    @classmethod
    async def for_scope(cls, org_id: UUID, query: ReportQuery, now: datetime) -> UsageReportOut:
        window = query.window(now)
        previous = ReportWindow(
            start_at=window.previous_start_at,
            end_at=window.previous_end_at,
            previous_start_at=window.previous_start_at,
            previous_end_at=window.previous_end_at,
            timezone=window.timezone,
        )
        comparison = await _totals(query.conditions(org_id, previous))
        granularity = "hour" if query.period == "today" else "day"
        bucket = func.date_trunc(granularity, col(UsageEvent.request_started_at), query.timezone).label("date")
        statement = (
            sql_select(
                bucket,
                func.count(func.distinct(col(UsageEvent.request_id))),
                func.coalesce(func.sum(col(UsageEvent.input_tokens)), 0),
                func.coalesce(func.sum(col(UsageEvent.output_tokens)), 0),
                func.coalesce(func.sum(col(UsageEvent.cost_usd)), ZERO_USD),
            )
            .where(*query.conditions(org_id, window))
            .group_by(bucket)
            .order_by(bucket)
        )
        daily = {
            values[0]: UsageDayOut(
                date=values[0],
                requests=values[1],
                input_tokens=values[2],
                output_tokens=values[3],
                cost_usd=values[4],
            )
            for values in (await current_session().execute(statement)).all()
        }
        days = [
            daily.get(start_at, UsageDayOut(date=start_at, requests=0, input_tokens=0, output_tokens=0, cost_usd=ZERO_USD))
            for start_at in _buckets(window, granularity)
        ]
        return cls(
            totals=UsageTotalsOut(
                requests=sum(day.requests for day in days),
                input_tokens=sum(day.input_tokens for day in days),
                output_tokens=sum(day.output_tokens for day in days),
                cost_usd=sum((day.cost_usd for day in days), ZERO_USD),
            ),
            comparison=comparison,
            daily=days,
            period=window,
            updated_at=now,
        )


async def _totals(conditions: list[ColumnElement[bool]]) -> UsageTotalsOut:
    statement = sql_select(
        func.count(func.distinct(col(UsageEvent.request_id))),
        func.coalesce(func.sum(col(UsageEvent.input_tokens)), 0),
        func.coalesce(func.sum(col(UsageEvent.output_tokens)), 0),
        func.coalesce(func.sum(col(UsageEvent.cost_usd)), ZERO_USD),
    ).where(*conditions)
    values = (await current_session().execute(statement)).one()
    return UsageTotalsOut(requests=values[0], input_tokens=values[1], output_tokens=values[2], cost_usd=values[3])


def _buckets(window: ReportWindow, granularity: str) -> list[datetime]:
    timezone = ZoneInfo(window.timezone)
    if granularity == "hour":
        first = window.start_at
        return [first + timedelta(hours=index) for index in range(int((window.end_at - first).total_seconds() // 3600) + 1)]
    local_day = window.start_at.astimezone(timezone).date()
    last_day = (window.end_at - timedelta(microseconds=1)).astimezone(timezone).date()
    return [
        datetime.combine(local_day + timedelta(days=index), datetime.min.time(), timezone).astimezone(UTC)
        for index in range((last_day - local_day).days + 1)
    ]
