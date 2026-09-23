from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator
from sqlmodel import col

from contract import UsageStatus
from control_plane.models.common.pagination import CursorToken
from control_plane.models.usage_event import UsageEvent

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement

Period = Literal["today", "7d", "30d", "month_to_date", "custom"]
Grouping = Literal["workspace", "owner", "key", "model", "provider", "credential"]
AttributionSort = Literal["cost", "change", "requests"]
FilterDimension = Grouping
MAX_REPORT_SPAN = timedelta(days=366)


class ReportWindow(BaseModel):
    start_at: datetime
    end_at: datetime
    previous_start_at: datetime
    previous_end_at: datetime
    timezone: str


class ReportQuery(BaseModel):
    workspace_id: UUID | None = None
    period: Period = "30d"
    timezone: str = "UTC"
    start_date: date | None = None
    end_date: date | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    owner_id: UUID | None = None
    key_id: str | None = None
    model_id: str | None = None
    provider_id: str | None = None
    credential_id: UUID | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, timezone: str) -> str:
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as error:
            message = "Unknown timezone"
            raise ValueError(message) from error
        return timezone

    @model_validator(mode="after")
    def valid_custom_period(self) -> ReportQuery:
        if self.period == "custom" and (self.start_date is None or self.end_date is None or self.start_date > self.end_date):
            message = "Custom period requires ordered dates"
            raise ValueError(message)
        if self.period != "custom" and (self.start_date is not None or self.end_date is not None):
            message = "Dates require period=custom"
            raise ValueError(message)
        if (
            self.period == "custom"
            and self.start_date is not None
            and self.end_date is not None
            and self.end_date - self.start_date >= MAX_REPORT_SPAN
        ):
            message = "Custom period cannot exceed 366 days"
            raise ValueError(message)
        if (self.start_at is None) != (self.end_at is None) or (
            self.start_at is not None and self.end_at is not None and self.start_at >= self.end_at
        ):
            message = "Bucket start_at and end_at must form an ordered pair"
            raise ValueError(message)
        if self.start_at is not None and self.end_at is not None and self.end_at - self.start_at > MAX_REPORT_SPAN:
            message = "Bucket window cannot exceed 366 days"
            raise ValueError(message)
        return self

    def window(self, now: datetime) -> ReportWindow:
        if self.start_at is not None and self.end_at is not None:
            duration = self.end_at - self.start_at
            return ReportWindow(
                start_at=self.start_at,
                end_at=self.end_at,
                previous_start_at=self.start_at - duration,
                previous_end_at=self.start_at,
                timezone=self.timezone,
            )
        timezone = ZoneInfo(self.timezone)
        local_now = now.astimezone(timezone)
        today = local_now.date()
        if self.period == "today":
            start_date = today
        elif self.period == "7d":
            start_date = today - timedelta(days=6)
        elif self.period == "30d":
            start_date = today - timedelta(days=29)
        elif self.period == "month_to_date":
            start_date = today.replace(day=1)
        else:
            start_date = self.start_date if self.start_date is not None else today
        start_at = datetime.combine(start_date, time.min, timezone).astimezone(UTC)
        end_at = (
            datetime.combine(self.end_date + timedelta(days=1), time.min, timezone).astimezone(UTC)
            if self.period == "custom" and self.end_date is not None
            else now
        )
        duration = end_at - start_at
        return ReportWindow(
            start_at=start_at,
            end_at=end_at,
            previous_start_at=start_at - duration,
            previous_end_at=start_at,
            timezone=self.timezone,
        )

    def conditions(self, org_id: UUID, window: ReportWindow | None = None) -> list[ColumnElement[bool]]:
        conditions = [col(UsageEvent.org_id) == org_id]
        if window is not None:
            conditions.extend(
                [
                    col(UsageEvent.request_started_at) >= window.start_at,
                    col(UsageEvent.request_started_at) < window.end_at,
                ]
            )
        if self.workspace_id is not None:
            conditions.append(col(UsageEvent.workspace_id) == self.workspace_id)
        if self.owner_id is not None:
            conditions.append(col(UsageEvent.user_id) == self.owner_id)
        if self.key_id is not None:
            conditions.append(col(UsageEvent.key_id) == self.key_id)
        if self.model_id is not None:
            conditions.append(col(UsageEvent.model_id) == self.model_id)
        if self.provider_id is not None:
            conditions.append(col(UsageEvent.provider_id) == self.provider_id)
        if self.credential_id is not None:
            conditions.append(col(UsageEvent.credential_id) == self.credential_id)
        return conditions


class AttributionQuery(ReportQuery):
    group_by: Grouping = "workspace"
    search: str | None = None
    sort_by: AttributionSort = "cost"
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class FilterOptionsQuery(ReportQuery):
    dimension: FilterDimension
    search: str | None = None


class RequestQuery(ReportQuery):
    request_id: UUID | None = None
    status: UsageStatus | None = None
    multiple_attempts: bool = False
    limit: int = Field(default=50, ge=1, le=100)
    cursor: CursorToken | None = None
