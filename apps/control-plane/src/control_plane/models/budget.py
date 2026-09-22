from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlmodel import col, select

from contract.budgets import BudgetBucket, BudgetState, KeyBudgetBucket, SharedBudgetBucket, budget_window
from contract.money import ZERO_USD, UsdAmount
from contract.policies import AllRequests, Budget, BudgetAggregation, BudgetPeriod, RequestMatch, RuleDefinition, SelectedKeys, SelectedUsers
from control_plane.db import current_session
from control_plane.models.policy import Policy, PolicyOut
from control_plane.models.usage_event import UsageEvent

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

    from sqlalchemy.sql.elements import ColumnElement
    from sqlalchemy.sql.selectable import Select


class BudgetUsagePage(BaseModel):
    rule_index: int | None = Field(default=None, ge=0, lt=100)
    bucket_id: str | None = Field(default=None, min_length=1, max_length=255)
    after_bucket: str | None = Field(default=None, min_length=1, max_length=255)
    limit: int = Field(default=100, ge=1, le=1000)


@dataclass(frozen=True)
class _BudgetRule:
    policy: Policy
    index: int
    definition: RuleDefinition
    action: Budget
    window_start: datetime
    window_end: datetime


def _budget_rules(policy: Policy, now: datetime) -> Iterator[_BudgetRule]:
    for index, definition in enumerate(policy.definition.rules):
        if isinstance(action := definition.action, Budget):
            window_start, window_end = budget_window(action.period, now)
            yield _BudgetRule(policy, index, definition, action, window_start, window_end)


async def _spending(budget: _BudgetRule, page: BudgetUsagePage | None = None) -> tuple[tuple[BudgetBucket, UsdAmount], ...]:
    spend = cast("ColumnElement[UsdAmount]", func.coalesce(func.sum(UsageEvent.cost_usd), ZERO_USD))
    filters = _budget_filters(budget)
    if budget.action.aggregation == "shared":
        result = await current_session().execute(select(spend).where(*filters))
        return ((SharedBudgetBucket(), result.scalar_one()),)
    bucket_column = cast("ColumnElement[object]", col(UsageEvent.key_id))
    statement = _bucket_statement(select(bucket_column, spend).where(*filters), spend, budget.action, bucket_column, page)
    result = await current_session().execute(statement)
    return tuple((KeyBudgetBucket(key_id=str(bucket_id)), amount) for bucket_id, amount in result.all())


def _budget_filters(budget: _BudgetRule) -> tuple[ColumnElement[bool], ...]:
    return (
        col(UsageEvent.org_id) == budget.policy.org_id,
        col(UsageEvent.workspace_id) == budget.policy.workspace_id,
        col(UsageEvent.occurred_at) >= budget.window_start,
        col(UsageEvent.occurred_at) < budget.window_end,
        *_target_filters(budget.policy),
        *_match_filters(budget.definition.match),
    )


def _target_filters(policy: Policy) -> tuple[ColumnElement[bool], ...]:
    target = policy.definition.target
    if isinstance(target, SelectedKeys):
        return (col(UsageEvent.key_id).in_(target.key_ids),)
    if isinstance(target, SelectedUsers):
        return (col(UsageEvent.user_id).in_(target.user_ids),)
    return ()


def _match_filters(match: AllRequests | RequestMatch) -> tuple[ColumnElement[bool], ...]:
    if not isinstance(match, RequestMatch):
        return ()
    return (
        *((col(UsageEvent.requested_model_id).in_(match.models),) if match.models else ()),
        *((col(UsageEvent.stream) == match.stream,) if match.stream is not None else ()),
        *((col(UsageEvent.requested_capabilities).op("@>")(list(match.capabilities)),) if match.capabilities else ()),
    )


def _bucket_statement(
    statement: Select, spend: ColumnElement[UsdAmount], action: Budget, bucket_column: ColumnElement[object], page: BudgetUsagePage | None
) -> Select:
    statement = statement.group_by(bucket_column).order_by(bucket_column)
    if page is None:
        return statement.having(spend >= action.amount_usd)
    if page.bucket_id is not None:
        statement = statement.where(bucket_column == page.bucket_id)
    if page.after_bucket is not None:
        statement = statement.where(bucket_column > page.after_bucket)
    return statement.limit(page.limit + 1)


async def budget_states(org_id: UUID, now: datetime) -> tuple[BudgetState, ...]:
    policies = await Policy.find(col(Policy.org_id) == org_id, col(Policy.enabled).is_(True))
    states: list[BudgetState] = []
    for policy in policies:
        states.extend(await enforcement_state(policy, now))
    return tuple(states)


async def enforcement_state(policy: Policy, now: datetime) -> tuple[BudgetState, ...]:
    states: list[BudgetState] = []
    for budget in _budget_rules(policy, now):
        spend = await _spending(budget)
        states.append(
            BudgetState(
                policy_id=policy.id,
                rule_index=budget.index,
                workspace_id=policy.workspace_id,
                target=policy.definition.target,
                match=budget.definition.match,
                aggregation=budget.action.aggregation,
                amount_usd=budget.action.amount_usd,
                period=budget.action.period,
                window_start=budget.window_start,
                window_end=budget.window_end,
                exhausted_buckets=tuple(bucket for bucket, amount in spend if amount >= budget.action.amount_usd),
            )
        )
    return tuple(states)


async def budget_status(policy: Policy, now: datetime, page: BudgetUsagePage) -> PolicyBudgetStatus:
    budgets: list[BudgetRuleStatus] = []
    for budget in _budget_rules(policy, now):
        if page.rule_index is not None and budget.index != page.rule_index:
            continue
        spend = await _spending(budget, page)
        if not spend and page.bucket_id is not None and page.after_bucket is None:
            spend = ((KeyBudgetBucket(key_id=page.bucket_id), ZERO_USD),)
        budgets.append(
            BudgetRuleStatus(
                rule_index=budget.index,
                aggregation=budget.action.aggregation,
                amount_usd=budget.action.amount_usd,
                period=budget.action.period,
                window_start=budget.window_start,
                window_end=budget.window_end,
                buckets=tuple(
                    BudgetBucketStatus(
                        bucket=bucket,
                        spent_usd=amount,
                        remaining_usd=max(ZERO_USD, budget.action.amount_usd - amount),
                        exhausted=amount >= budget.action.amount_usd,
                    )
                    for bucket, amount in spend[: page.limit]
                ),
                next_bucket=spend[page.limit - 1][0] if len(spend) > page.limit else None,
            )
        )
    return PolicyBudgetStatus(policy=PolicyOut.model_validate(policy), computed_at=now, budgets=tuple(budgets))


class BudgetBucketStatus(BaseModel):
    bucket: BudgetBucket
    spent_usd: UsdAmount
    remaining_usd: UsdAmount
    exhausted: bool


class BudgetRuleStatus(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    rule_index: int = Field(ge=0, lt=100)
    aggregation: BudgetAggregation
    amount_usd: UsdAmount = Field(gt=0)
    period: BudgetPeriod
    window_start: datetime
    window_end: datetime
    buckets: tuple[BudgetBucketStatus, ...]
    next_bucket: BudgetBucket | None


class PolicyBudgetStatus(BaseModel):
    policy: PolicyOut
    computed_at: datetime
    budgets: tuple[BudgetRuleStatus, ...]
