from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from contract.money import UsdAmount
from contract.policies import BudgetPeriod, PolicyIdentifier, PolicyMatch, PolicyTarget


class _BudgetState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)

    policy_id: UUID
    rule_index: int = Field(ge=0, lt=100)
    workspace_id: UUID
    target: PolicyTarget
    match: PolicyMatch
    amount_usd: UsdAmount = Field(gt=0)
    period: BudgetPeriod
    window_start: AwareDatetime
    window_end: AwareDatetime

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if (self.window_start, self.window_end) != budget_window(self.period, self.window_start):
            message = "Budget state must describe a complete UTC calendar window"
            raise ValueError(message)
        return self


class SharedBudgetState(_BudgetState):
    sharing: Literal["shared"] = "shared"
    exhausted: bool


class PerKeyBudgetState(_BudgetState):
    sharing: Literal["per_key"] = "per_key"
    exhausted_key_ids: frozenset[PolicyIdentifier]


BudgetState = Annotated[SharedBudgetState | PerKeyBudgetState, Field(discriminator="sharing")]


class PolicyStateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)

    org_ids: tuple[UUID, ...] = Field(min_length=1, max_length=1000, description="Organizations whose current budget state is requested")

    @model_validator(mode="after")
    def unique_orgs(self) -> Self:
        if len(self.org_ids) != len(set(self.org_ids)):
            message = "Organizations must be unique"
            raise ValueError(message)
        return self


class OrgPolicyState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)

    org_id: UUID
    budgets: tuple[BudgetState, ...]

    @model_validator(mode="after")
    def unique_rules(self) -> Self:
        if len({(budget.policy_id, budget.rule_index) for budget in self.budgets}) != len(self.budgets):
            message = "Budget rules must be unique within an organization"
            raise ValueError(message)
        return self


class PolicyState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)

    computed_at: AwareDatetime
    organizations: tuple[OrgPolicyState, ...]

    @model_validator(mode="after")
    def unique_orgs(self) -> Self:
        if len({org.org_id for org in self.organizations}) != len(self.organizations):
            message = "Organizations must be unique"
            raise ValueError(message)
        return self


def budget_window(period: BudgetPeriod, now: datetime) -> tuple[datetime, datetime]:
    now = now.astimezone(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return start, start + timedelta(days=1)
    start = start.replace(day=1)
    return start, (start.replace(day=28) + timedelta(days=4)).replace(day=1)
