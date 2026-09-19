from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Self
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Column, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, col, select

from contract import CredentialScope, UsageStatus, UsdAmount
from contract.budgets import budget_window
from contract.model_types import RequestCapability
from contract.money import ZERO_USD
from contract.policies import Budget, RequestMatch, RuleDefinition, SelectedKeys, SelectedUsers
from control_plane.db import current_session
from control_plane.models.common import PageQuery, PageSlice, keyset_page
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut

if TYPE_CHECKING:
    from control_plane.models.policy import Policy


class BudgetUsagePage(BaseModel):
    rule_index: int | None = Field(default=None, ge=0, lt=100)
    key_id: str | None = Field(default=None, min_length=1, max_length=255)
    after_key: str | None = Field(default=None, min_length=1, max_length=255)
    limit: int = Field(default=100, ge=1, le=1000)


class UsageEvent(Record, table=True):
    __table_args__: ClassVar = (
        Index("usage_event_org_occurred_event_idx", "org_id", "occurred_at", "event_id"),
        Index("usage_event_org_workspace_occurred_event_idx", "org_id", "workspace_id", "occurred_at", "event_id"),
        Index("usage_event_org_event_idx", "org_id", "event_id"),
        Index("usage_event_org_workspace_event_idx", "org_id", "workspace_id", "event_id"),
    )

    event_id: UUID = Field(primary_key=True)
    request_id: UUID
    occurred_at: datetime = Field(sa_type=UTCDateTime)
    org_id: UUID
    workspace_id: UUID
    key_id: str
    user_id: UUID
    requested_model_id: str
    requested_capabilities: list[RequestCapability] = Field(sa_column=Column(ARRAY(String), nullable=False))
    model_id: str
    provider_id: str
    bundle_id: UUID
    input_tokens: int
    output_tokens: int
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
    async def for_scope(
        cls,
        org_id: UUID,
        workspace_id: UUID | None,
        page: PageQuery,
    ) -> PageSlice[Self]:
        statement = select(cls).where(cls.org_id == org_id)
        if workspace_id is not None:
            statement = statement.where(cls.workspace_id == workspace_id)
        return await keyset_page(
            statement,
            page,
            col(cls.event_id),
            UUID,
        )

    @classmethod
    async def budget_spend(
        cls, policy: Policy, rule: RuleDefinition, now: datetime, page: BudgetUsagePage | None = None
    ) -> list[tuple[str | None, UsdAmount]]:
        action = rule.action
        if not isinstance(action, Budget):
            message = "Spending requires a budget rule"
            raise TypeError(message)
        start, end = budget_window(action.period, now)
        spend = func.coalesce(func.sum(cls.cost_usd), ZERO_USD)
        statement = select(col(cls.key_id), spend) if action.sharing == "per_key" else select(spend)
        statement = statement.where(
            cls.org_id == policy.org_id, cls.workspace_id == policy.workspace_id, cls.occurred_at >= start, cls.occurred_at < end
        )
        target = policy.definition.target
        if isinstance(target, SelectedKeys):
            statement = statement.where(col(cls.key_id).in_(target.key_ids))
        elif isinstance(target, SelectedUsers):
            statement = statement.where(col(cls.user_id).in_(target.user_ids))
        match = rule.match
        if isinstance(match, RequestMatch) and match.models:
            statement = statement.where(col(cls.requested_model_id).in_(match.models))
        if isinstance(match, RequestMatch) and match.stream is not None:
            statement = statement.where(cls.stream == match.stream)
        if isinstance(match, RequestMatch) and match.capabilities:
            statement = statement.where(col(cls.requested_capabilities).op("@>")(list(match.capabilities)))
        if action.sharing == "per_key":
            statement = statement.group_by(col(cls.key_id)).order_by(col(cls.key_id))
            if page is None:
                statement = statement.having(spend >= action.amount_usd)
            else:
                if page.key_id is not None:
                    statement = statement.where(cls.key_id == page.key_id)
                if page.after_key is not None:
                    statement = statement.where(cls.key_id > page.after_key)
                statement = statement.limit(page.limit + 1)
        result = await current_session().execute(statement)
        if action.sharing == "shared":
            return [(None, result.scalar_one())]
        return [(key_id, amount) for key_id, amount in result.all()]


class UsageEventOut(RecordOut[UsageEvent]):
    event_id: UUID
    request_id: UUID
    occurred_at: datetime
    org_id: UUID
    workspace_id: UUID
    key_id: str
    user_id: UUID
    requested_model_id: str
    requested_capabilities: list[RequestCapability]
    model_id: str
    provider_id: str
    bundle_id: UUID
    input_tokens: int
    output_tokens: int
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


class EventsIngestedOut(BaseModel):
    received: int
    ingested: int
