from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import col

from contract.budgets import BudgetBucket, BudgetState, budget_window
from contract.money import ZERO_USD, UsdAmount
from contract.policies import Budget, BudgetAggregation, BudgetPeriod
from control_plane.models.policy import Policy, PolicyOut
from control_plane.models.usage_event import BudgetUsagePage, UsageEvent

if TYPE_CHECKING:
    from uuid import UUID


async def budget_states(org_id: UUID, now: datetime) -> tuple[BudgetState, ...]:
    policies = await Policy.find(col(Policy.org_id) == org_id, col(Policy.enabled).is_(True))
    states: list[BudgetState] = []
    for policy in policies:
        states.extend(await enforcement_state(policy, now))
    return tuple(states)


async def enforcement_state(policy: Policy, now: datetime) -> tuple[BudgetState, ...]:
    states: list[BudgetState] = []
    for index, rule in enumerate(policy.definition.rules):
        if not isinstance(action := rule.action, Budget):
            continue
        start, end = budget_window(action.period, now)
        spend = await UsageEvent.budget_spend(policy, rule, now)
        states.append(
            BudgetState(
                policy_id=policy.id,
                rule_index=index,
                workspace_id=policy.workspace_id,
                target=policy.definition.target,
                match=rule.match,
                aggregation=action.aggregation,
                amount_usd=action.amount_usd,
                period=action.period,
                window_start=start,
                window_end=end,
                exhausted_buckets=tuple(bucket for bucket, amount in spend if amount >= action.amount_usd),
            )
        )
    return tuple(states)


async def budget_status(policy: Policy, now: datetime, page: BudgetUsagePage) -> PolicyBudgetStatus:
    budgets: list[BudgetRuleStatus] = []
    for index, rule in enumerate(policy.definition.rules):
        if page.rule_index is not None and index != page.rule_index:
            continue
        if not isinstance(action := rule.action, Budget):
            continue
        start, end = budget_window(action.period, now)
        spend = await UsageEvent.budget_spend(policy, rule, now, page)
        if not spend and page.bucket_id is not None and page.after_bucket is None:
            spend = [(UsageEvent.budget_bucket(action.aggregation, page.bucket_id), ZERO_USD)]
        budgets.append(
            BudgetRuleStatus(
                rule_index=index,
                aggregation=action.aggregation,
                amount_usd=action.amount_usd,
                period=action.period,
                window_start=start,
                window_end=end,
                buckets=tuple(
                    BudgetBucketStatus(
                        bucket=bucket,
                        spent_usd=amount,
                        remaining_usd=max(ZERO_USD, action.amount_usd - amount),
                        exhausted=amount >= action.amount_usd,
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
