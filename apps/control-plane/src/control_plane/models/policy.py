from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Self, override
from uuid import UUID

from pydantic import field_validator, model_validator
from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, Index, TypeDecorator, text
from sqlmodel import Field, col, select

from contract.policies import (
    MAX_WORKSPACE_RULES,
    PolicyDefinition,
    PolicyEntry,
    SelectedKeys,
)
from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.common import Identified, NotOwnedError, OrgOwned, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordCreate, RecordOut, RecordUpdate, RequestModel
from control_plane.models.inference_key import InferenceKey
from control_plane.models.runtime_configuration import bundle_input

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect


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
@bundle_input(scope="org", columns=("org_id", "workspace_id", "name", "enabled", "priority", "definition"))
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
        if self.enabled:
            active_policies = select(Policy).where(
                col(Policy.workspace_id) == self.workspace_id, col(Policy.enabled).is_(True), col(Policy.id) != self.id
            )
            policies = (await current_session().execute(active_policies)).scalars()
            if sum(len(policy.definition.rule_ids) for policy in policies) + len(self.definition.rule_ids) > MAX_WORKSPACE_RULES:
                msg = f"A workspace may contain at most {MAX_WORKSPACE_RULES} active policy rules"
                raise InvalidPolicyError(msg)
        target = self.definition.target
        if isinstance(target, SelectedKeys):
            keys = await InferenceKey.find(InferenceKey.workspace_id == self.workspace_id)
            if set(target.key_ids) - {str(key.id) for key in keys}:
                msg = "Selected inference keys must belong to this workspace"
                raise InvalidPolicyError(msg)
        from control_plane.models.rule import Rule  # noqa: PLC0415 policies reference reusable rules

        rules = await Rule.find(col(Rule.id).in_(self.definition.rule_ids))
        if set(self.definition.rule_ids) != {rule.id for rule in rules} or any(rule.workspace_id != self.workspace_id for rule in rules):
            msg = "Policy rules must belong to this workspace"
            raise InvalidPolicyError(msg)

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
    definition: PolicyDefinition = Field(description="Inference key target and ordered rules. Budgets are not yet enforced")


class PolicyUpdate(RecordUpdate[Policy]):
    name: str | None = Field(default=None, min_length=1, max_length=200, description="Replacement display name; omit to leave unchanged")
    enabled: bool | None = Field(default=None, description="Enable or disable this policy; omit to leave unchanged")
    priority: int | None = Field(default=None, ge=0, le=10000, description="Replacement priority, with lower numbers first; omit to leave unchanged")
    definition: PolicyDefinition | None = Field(default=None, description="Replace the complete target and ordered rules; omit to leave unchanged")

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
