from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Self, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Column, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, col, select

from contract import CredentialScope, UsageStatus, UsdAmount
from contract.budgets import BudgetBucket, KeyBudgetBucket, SharedBudgetBucket, UserBudgetBucket, budget_window
from contract.model_types import RequestCapability
from contract.money import ZERO_USD
from contract.policies import AllRequests, Budget, BudgetScope, RequestMatch, RuleDefinition, SelectedKeys, SelectedUsers
from control_plane.db import current_session
from control_plane.models.common import PageQuery, PageSlice, keyset_page
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.common.wire import RecordOut

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement
    from sqlalchemy.sql.selectable import Select

    from control_plane.models.policy import Policy


class BudgetUsagePage(BaseModel):
    rule_index: int | None = Field(default=None, ge=0, lt=100)
    bucket_id: str | None = Field(default=None, min_length=1, max_length=255)
    after_bucket: str | None = Field(default=None, min_length=1, max_length=255)
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
    ) -> list[tuple[BudgetBucket, UsdAmount]]:
        action = rule.action
        if not isinstance(action, Budget):
            message = "Spending requires a budget rule"
            raise TypeError(message)
        start, end = budget_window(action.period, now)
        spend = func.coalesce(func.sum(cls.cost_usd), ZERO_USD)
        bucket_column = cls._bucket_column(action.scope)
        statement = select(spend) if bucket_column is None else select(bucket_column, spend)
        statement = statement.where(*cls._budget_filters(policy, rule, start, end))
        if bucket_column is not None:
            statement = cls._bucket_statement(statement, spend, action, bucket_column, page)
        result = await current_session().execute(statement)
        if bucket_column is None:
            return [(SharedBudgetBucket(), result.scalar_one())]
        return [(cls.budget_bucket(action.scope, bucket_id), amount) for bucket_id, amount in result.all()]

    @classmethod
    def _bucket_column(cls, scope: BudgetScope) -> ColumnElement[object] | None:
        return {
            "shared": None,
            "per_key": cast("ColumnElement[object]", col(cls.key_id)),
            "per_user": cast("ColumnElement[object]", col(cls.user_id)),
        }[scope]

    @staticmethod
    def budget_bucket(scope: BudgetScope, bucket_id: object | None = None) -> BudgetBucket:
        if scope == "shared":
            return SharedBudgetBucket()
        if scope == "per_key":
            return KeyBudgetBucket(key_id=str(bucket_id))
        return UserBudgetBucket(user_id=UUID(str(bucket_id)))

    @classmethod
    def _budget_filters(cls, policy: Policy, rule: RuleDefinition, start: datetime, end: datetime) -> tuple[ColumnElement[bool], ...]:
        return (
            col(cls.org_id) == policy.org_id,
            col(cls.workspace_id) == policy.workspace_id,
            col(cls.occurred_at) >= start,
            col(cls.occurred_at) < end,
            *cls._target_filters(policy),
            *cls._match_filters(rule.match),
        )

    @classmethod
    def _target_filters(cls, policy: Policy) -> tuple[ColumnElement[bool], ...]:
        target = policy.definition.target
        if isinstance(target, SelectedKeys):
            return (col(cls.key_id).in_(target.key_ids),)
        if isinstance(target, SelectedUsers):
            return (col(cls.user_id).in_(target.user_ids),)
        return ()

    @classmethod
    def _match_filters(cls, match: AllRequests | RequestMatch) -> tuple[ColumnElement[bool], ...]:
        if not isinstance(match, RequestMatch):
            return ()
        return (
            *((col(cls.requested_model_id).in_(match.models),) if match.models else ()),
            *((col(cls.stream) == match.stream,) if match.stream is not None else ()),
            *((col(cls.requested_capabilities).op("@>")(list(match.capabilities)),) if match.capabilities else ()),
        )

    @classmethod
    def _bucket_statement(
        cls, statement: Select, spend: ColumnElement[UsdAmount], action: Budget, bucket_column: ColumnElement[object], page: BudgetUsagePage | None
    ) -> Select:
        statement = statement.group_by(bucket_column).order_by(bucket_column)
        if page is None:
            return statement.having(spend >= action.amount_usd)
        if page.bucket_id is not None:
            statement = statement.where(bucket_column == cls._bucket_value(action.scope, page.bucket_id))
        if page.after_bucket is not None:
            statement = statement.where(bucket_column > cls._bucket_value(action.scope, page.after_bucket))
        return statement.limit(page.limit + 1)

    @staticmethod
    def _bucket_value(scope: BudgetScope, bucket_id: str) -> str | UUID:
        return UUID(bucket_id) if scope == "per_user" else bucket_id


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
