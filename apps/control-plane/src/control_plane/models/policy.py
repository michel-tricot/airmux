from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated, ClassVar, Literal, Self, TypedDict, override
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, TypeDecorator, text
from sqlmodel import Field, col, select

from contract.budgets import BudgetState, PerKeyBudgetState, SharedBudgetState, budget_window
from contract.money import ZERO_USD, UsdAmount
from contract.policies import (
    MAX_WORKSPACE_RULES,
    AllowedModels,
    AllowedProviders,
    Budget,
    BudgetPeriod,
    Fallback,
    PolicyDefinition,
    PolicyEntry,
    PolicyIdentifier,
    PolicyMatch,
    PolicyTarget,
    RequestMatch,
    RuleDefinition,
    SelectedKeys,
    SelectedUsers,
)
from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.bundle_input import bundle_input
from control_plane.models.common import Identified, NotOwnedError, OrgOwned, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordCreate, RecordOut, RecordUpdate, RequestModel
from control_plane.models.inference_key import InferenceKey
from control_plane.models.model import Model
from control_plane.models.provider import Provider
from control_plane.models.usage_event import BudgetUsagePage, UsageEvent
from control_plane.models.user import User

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect


class _BudgetStateFields(TypedDict):
    policy_id: UUID
    rule_index: int
    workspace_id: UUID
    target: PolicyTarget
    match: PolicyMatch
    amount_usd: UsdAmount
    period: BudgetPeriod
    window_start: datetime
    window_end: datetime


class PolicyDefinitionType(TypeDecorator[PolicyDefinition]):
    impl = JSON
    cache_ok = True

    @override
    def process_bind_param(self, value: PolicyDefinition | None, dialect: Dialect) -> dict[str, object] | None:
        return value.model_dump(mode="json") if value is not None else None

    @override
    def process_result_value(self, value: object, dialect: Dialect) -> PolicyDefinition:
        return PolicyDefinition.model_validate(value)


@audited
@bundle_input(scope="org")
class Policy(Record, Identified, OrgOwned, Tombstonable, table=True):
    __table_args__: ClassVar = (
        ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"]),
        CheckConstraint("priority >= 0 AND priority <= 10000", name="policy_priority_valid"),
        Index("policy_workspace_priority_id_idx", "workspace_id", "priority", "id"),
        Index("policy_active_workspace_id_idx", "workspace_id", "id", postgresql_where=text("enabled")),
        Index("policy_active_org_id_idx", "org_id", "id", postgresql_where=text("enabled")),
    )

    org_id: UUID = Field(foreign_key="org.id")
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    definition: PolicyDefinition = Field(sa_type=PolicyDefinitionType, nullable=False)

    api_readonly: ClassVar[frozenset[str]] = frozenset({"workspace_id"})

    @classmethod
    async def budget_states(cls, org_id: UUID, now: datetime) -> tuple[BudgetState, ...]:
        policies = await cls.find(cls.org_id == org_id, col(cls.enabled).is_(True))
        states: list[BudgetState] = []
        for policy in policies:
            states.extend(await policy.enforcement_state(now))
        return tuple(states)

    async def enforcement_state(self, now: datetime) -> tuple[BudgetState, ...]:
        states: list[BudgetState] = []
        for index, rule in enumerate(self.definition.rules):
            state = await self._enforcement_state_for_rule(index, rule, now)
            if state is not None:
                states.append(state)
        return tuple(states)

    async def _enforcement_state_for_rule(self, index: int, rule: RuleDefinition, now: datetime) -> BudgetState | None:
        action = rule.action
        if not isinstance(action, Budget):
            return None
        start, end = budget_window(action.period, now)
        spend = await UsageEvent.budget_spend(self, rule, now)
        common: _BudgetStateFields = {
            "policy_id": self.id,
            "rule_index": index,
            "workspace_id": self.workspace_id,
            "target": self.definition.target,
            "match": rule.match,
            "amount_usd": action.amount_usd,
            "period": action.period,
            "window_start": start,
            "window_end": end,
        }
        if action.sharing == "shared":
            return SharedBudgetState(**common, exhausted=spend[0][1] >= action.amount_usd)
        return PerKeyBudgetState(**common, exhausted_key_ids=frozenset(key_id for key_id, _ in spend if key_id is not None))

    async def budget_status(self, now: datetime, page: BudgetUsagePage) -> PolicyBudgetStatus:
        budgets: list[SharedBudgetStatus | PerKeyBudgetStatus] = []
        for index, rule in enumerate(self.definition.rules):
            if not self._includes_rule(index, page):
                continue
            budget = await self._budget_status_for_rule(index, rule, now, page)
            if budget is not None:
                budgets.append(budget)
        return PolicyBudgetStatus(policy=PolicyOut.model_validate(self), computed_at=now, budgets=tuple(budgets))

    @staticmethod
    def _includes_rule(index: int, page: BudgetUsagePage) -> bool:
        return page.rule_index is None or index == page.rule_index

    async def _budget_status_for_rule(
        self, index: int, rule: RuleDefinition, now: datetime, page: BudgetUsagePage
    ) -> SharedBudgetStatus | PerKeyBudgetStatus | None:
        action = rule.action
        if not isinstance(action, Budget):
            return None
        start, end = budget_window(action.period, now)
        spend = await UsageEvent.budget_spend(self, rule, now, page)
        if action.sharing == "shared":
            return self._shared_budget_status(index, action, start, end, spend[0][1])
        return self._per_key_budget_status(index, action, (start, end), spend, page)

    @staticmethod
    def _shared_budget_status(index: int, action: Budget, start: datetime, end: datetime, spent: UsdAmount) -> SharedBudgetStatus:
        return SharedBudgetStatus(
            rule_index=index,
            amount_usd=action.amount_usd,
            period=action.period,
            window_start=start,
            window_end=end,
            spent_usd=spent,
            remaining_usd=max(ZERO_USD, action.amount_usd - spent),
            exhausted=spent >= action.amount_usd,
        )

    @staticmethod
    def _per_key_budget_status(
        index: int,
        action: Budget,
        window: tuple[datetime, datetime],
        spend: list[tuple[str | None, UsdAmount]],
        page: BudgetUsagePage,
    ) -> PerKeyBudgetStatus:
        start, end = window
        if not spend and page.key_id is not None and page.after_key is None:
            spend = [(page.key_id, ZERO_USD)]
        return PerKeyBudgetStatus(
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

    @classmethod
    async def in_workspace(cls, org_id: UUID, workspace_id: UUID, policy_id: UUID) -> Self:
        policy = await cls.owned_by(org_id, policy_id)
        if policy.workspace_id != workspace_id:
            raise NotOwnedError
        return policy

    @classmethod
    async def for_workspace(cls, workspace_id: UUID) -> list[Self]:
        return await cls.find(cls.workspace_id == workspace_id, order_by=(col(cls.priority), col(cls.id)))

    @classmethod
    async def reorder(cls, org_id: UUID, workspace_id: UUID, policy_ids: tuple[UUID, ...]) -> list[Self]:
        from control_plane.models.workspace import Workspace  # noqa: PLC0415 workspace deletion also depends on Policy

        session = current_session()
        workspace = (
            await session.execute(select(Workspace).where(col(Workspace.id) == workspace_id, col(Workspace.org_id) == org_id).with_for_update())
        ).scalar_one_or_none()
        if workspace is None:
            raise NotOwnedError
        policies = await cls.for_workspace(workspace_id)
        if len(policy_ids) != len(policies) or set(policy_ids) != {policy.id for policy in policies}:
            msg = "Policy order must contain every workspace policy exactly once"
            raise InvalidPolicyError(msg)
        policies_by_id = {policy.id: policy for policy in policies}
        ordered = [policies_by_id[policy_id] for policy_id in policy_ids]
        for priority, policy in enumerate(ordered):
            policy.priority = priority
            session.add(policy)
        await session.flush()
        return ordered

    @override
    async def save(self) -> Self:
        from control_plane.models.workspace import Workspace  # noqa: PLC0415 workspace deletion also depends on Policy

        session = current_session()
        with session.no_autoflush:
            await session.execute(select(Workspace.id).where(col(Workspace.id) == self.workspace_id).with_for_update())
            await self._validate_configuration()
            return await super().save()

    async def _validate_configuration(self) -> None:
        await self._validate_workspace_capacity()
        await self._validate_target()
        self._validate_rule_invariants()
        await self._validate_catalog_references()

    async def _validate_workspace_capacity(self) -> None:
        if not self.enabled:
            return
        active_policies = select(Policy).where(
            col(Policy.workspace_id) == self.workspace_id, col(Policy.enabled).is_(True), col(Policy.id) != self.id
        )
        policies = (await current_session().execute(active_policies)).scalars()
        total_rules = sum(len(policy.definition.rules) for policy in policies) + len(self.definition.rules)
        if total_rules > MAX_WORKSPACE_RULES:
            msg = f"A workspace may contain at most {MAX_WORKSPACE_RULES} active policy rules"
            raise InvalidPolicyError(msg)

    async def _validate_target(self) -> None:
        target = self.definition.target
        if isinstance(target, SelectedKeys):
            keys = await InferenceKey.find(InferenceKey.workspace_id == self.workspace_id)
            if set(target.key_ids).issubset({str(key.id) for key in keys}):
                return
            msg = "Selected inference keys must belong to this workspace"
            raise InvalidPolicyError(msg)
        if isinstance(target, SelectedUsers):
            users = await User.policy_candidates(self.org_id, self.workspace_id)
            if set(target.user_ids).issubset({user.id for user in users}):
                return
            msg = "Selected users must belong to this organization and be eligible for this workspace"
            raise InvalidPolicyError(msg)

    def _validate_rule_invariants(self) -> None:
        rules = self.definition.rules
        if len(set(rules)) != len(rules):
            msg = "Policy rules must be unique"
            raise InvalidPolicyError(msg)
        if sum(isinstance(rule.action, Fallback) for rule in rules) > 1:
            msg = "A policy may contain at most one fallback rule"
            raise InvalidPolicyError(msg)

    async def _validate_catalog_references(self) -> None:
        model_names = self._model_names()
        if model_names:
            models = await Model.find(col(Model.name).in_(model_names))
            if model_names != {model.name for model in models}:
                msg = "Policy models must exist in the catalog"
                raise InvalidPolicyError(msg)
        provider_names = self._provider_names()
        if provider_names:
            providers = await Provider.find(col(Provider.name).in_(provider_names))
            if provider_names != {provider.name for provider in providers}:
                msg = "Policy providers must exist in the catalog"
                raise InvalidPolicyError(msg)

    def _model_names(self) -> set[str]:
        return {
            name
            for rule in self.definition.rules
            for name in (
                *(rule.match.models if isinstance(rule.match, RequestMatch) else ()),
                *(rule.action.names if isinstance(rule.action, AllowedModels) else ()),
                *(rule.action.models if isinstance(rule.action, Fallback) else ()),
            )
        }

    def _provider_names(self) -> set[str]:
        return {name for rule in self.definition.rules if isinstance(rule.action, AllowedProviders) for name in rule.action.names}

    def entry(self) -> PolicyEntry:
        return PolicyEntry(id=self.id, workspace_id=self.workspace_id, name=self.name, priority=self.priority, definition=self.definition)


class InvalidPolicyError(ValueError):
    pass


class PolicyOrder(RequestModel):
    policy_ids: tuple[UUID, ...] = Field(description="Every workspace policy ID, from first to last evaluation priority")

    @field_validator("policy_ids")
    @classmethod
    def unique_policy_ids(cls, policy_ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(policy_ids) != len(set(policy_ids)):
            msg = "Policy order cannot contain duplicate policy IDs"
            raise ValueError(msg)
        return policy_ids


class PolicyCreate(RecordCreate[Policy]):
    name: str = Field(min_length=1, max_length=200, description="Display name for the workspace policy")
    enabled: bool = Field(default=True, description="Whether gateways apply this policy after receiving the updated configuration")
    priority: int = Field(default=100, ge=0, le=10000, description="Lower numbers run first; policy ID breaks ties. All matching restrictions apply")
    definition: PolicyDefinition = Field(description="Workspace, user, or inference key target and inline rules")


class PolicyUpdate(RecordUpdate[Policy]):
    name: str | None = Field(default=None, min_length=1, max_length=200, description="Replacement display name; omit to leave unchanged")
    enabled: bool | None = Field(default=None, description="Enable or disable this policy; omit to leave unchanged")
    priority: int | None = Field(default=None, ge=0, le=10000, description="Replacement priority, with lower numbers first; omit to leave unchanged")
    definition: PolicyDefinition | None = Field(default=None, description="Replace the complete target and inline rules; omit to leave unchanged")

    @model_validator(mode="after")
    def nonnull_changes(self) -> Self:
        if any(getattr(self, field) is None for field in self.model_fields_set):
            msg = "Policy fields cannot be null"
            raise ValueError(msg)
        return self


class PolicyOut(RecordOut[Policy]):
    id: UUID
    org_id: UUID
    workspace_id: UUID
    name: str
    enabled: bool
    priority: int
    definition: PolicyDefinition
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


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
