from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import col

from contract.budgets import BudgetState, PerKeyBudgetState, SharedBudgetState, budget_window
from contract.money import ZERO_USD, UsdAmount
from contract.policies import Budget, BudgetPeriod, PolicyIdentifier
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
        if action.sharing == "shared":
            states.append(
                SharedBudgetState(
                    policy_id=policy.id,
                    rule_index=index,
                    workspace_id=policy.workspace_id,
                    target=policy.definition.target,
                    match=rule.match,
                    amount_usd=action.amount_usd,
                    period=action.period,
                    window_start=start,
                    window_end=end,
                    exhausted=spend[0][1] >= action.amount_usd,
                )
            )
            continue
        states.append(
            PerKeyBudgetState(
                policy_id=policy.id,
                rule_index=index,
                workspace_id=policy.workspace_id,
                target=policy.definition.target,
                match=rule.match,
                amount_usd=action.amount_usd,
                period=action.period,
                window_start=start,
                window_end=end,
                exhausted_key_ids=frozenset(key_id for key_id, _ in spend if key_id is not None),
            )
        )
    return tuple(states)


async def budget_status(policy: Policy, now: datetime, page: BudgetUsagePage) -> PolicyBudgetStatus:
    budgets: list[SharedBudgetStatus | PerKeyBudgetStatus] = []
    for index, rule in enumerate(policy.definition.rules):
        if page.rule_index is not None and index != page.rule_index:
            continue
        if not isinstance(action := rule.action, Budget):
            continue
        start, end = budget_window(action.period, now)
        spend = await UsageEvent.budget_spend(policy, rule, now, page)
        if action.sharing == "shared":
            amount = spend[0][1]
            budgets.append(
                SharedBudgetStatus(
                    rule_index=index,
                    amount_usd=action.amount_usd,
                    period=action.period,
                    window_start=start,
                    window_end=end,
                    spent_usd=amount,
                    remaining_usd=max(ZERO_USD, action.amount_usd - amount),
                    exhausted=amount >= action.amount_usd,
                )
            )
            continue
        if not spend and page.key_id is not None and page.after_key is None:
            spend = [(page.key_id, ZERO_USD)]
        budgets.append(
            PerKeyBudgetStatus(
                rule_index=index,
                amount_usd=action.amount_usd,
                period=action.period,
                window_start=start,
                window_end=end,
                keys=tuple(
                    KeyBudgetStatus(
                        key_id=key_id,
                        spent_usd=amount,
                        remaining_usd=max(ZERO_USD, action.amount_usd - amount),
                        exhausted=amount >= action.amount_usd,
                    )
                    for key_id, amount in spend[: page.limit]
                    if key_id is not None
                ),
                next_key=spend[page.limit - 1][0] if len(spend) > page.limit else None,
            )
        )
    return PolicyBudgetStatus(policy=PolicyOut.model_validate(policy), computed_at=now, budgets=tuple(budgets))


class _BudgetStatus(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    rule_index: int = Field(ge=0, lt=100)
    amount_usd: UsdAmount = Field(gt=0)
    period: BudgetPeriod
    window_start: datetime
    window_end: datetime


class SharedBudgetStatus(_BudgetStatus):
    sharing: Literal["shared"] = "shared"
    spent_usd: UsdAmount
    remaining_usd: UsdAmount
    exhausted: bool


class KeyBudgetStatus(BaseModel):
    key_id: PolicyIdentifier
    spent_usd: UsdAmount
    remaining_usd: UsdAmount
    exhausted: bool


class PerKeyBudgetStatus(_BudgetStatus):
    sharing: Literal["per_key"] = "per_key"
    keys: tuple[KeyBudgetStatus, ...]
    next_key: PolicyIdentifier | None


class PolicyBudgetStatus(BaseModel):
    policy: PolicyOut
    computed_at: datetime
    budgets: tuple[Annotated[SharedBudgetStatus | PerKeyBudgetStatus, Field(discriminator="sharing")], ...]
