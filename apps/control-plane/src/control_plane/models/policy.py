from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Self, override
from uuid import UUID

from pydantic import field_validator, model_validator
from sqlalchemy import JSON, CheckConstraint, ForeignKeyConstraint, TypeDecorator
from sqlmodel import Field, col

from contract.policies import (
    MAX_WORKSPACE_POLICIES,
    AllowedModels,
    AllowedProviders,
    Fallback,
    PolicyDefinition,
    PolicyEntry,
    SelectedKeys,
    compile_condition,
)
from control_plane.models.audit import audited
from control_plane.models.common import Identified, NotOwnedError, OrgOwned, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordCreate, RecordOut, RecordUpdate
from control_plane.models.inference_key import InferenceKey
from control_plane.models.model import Model
from control_plane.models.provider import Provider
from control_plane.models.runtime_configuration import runtime_configured

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
@runtime_configured(scope="org", columns=("org_id", "workspace_id", "name", "enabled", "priority", "definition"))
class Policy(Record, Identified, OrgOwned, Tombstonable, table=True):
    __table_args__: ClassVar = (
        ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"]),
        CheckConstraint("priority >= 0 AND priority <= 10000", name="policy_priority_valid"),
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

    async def validate_configuration(self) -> None:
        target = self.definition.target
        if isinstance(target, SelectedKeys):
            keys = await InferenceKey.find(InferenceKey.workspace_id == self.workspace_id)
            if set(target.key_ids) - {str(key.id) for key in keys}:
                msg = "Selected inference keys must belong to this workspace"
                raise InvalidPolicyError(msg)
        action = self.definition.action
        if isinstance(action, AllowedModels | Fallback):
            names = action.names if isinstance(action, AllowedModels) else action.models
            models = await Model.find(col(Model.name).in_(names))
            if set(names) != {model.name for model in models}:
                msg = "Policy models must exist in the catalog"
                raise InvalidPolicyError(msg)
        if isinstance(action, AllowedProviders):
            providers = await Provider.find(col(Provider.name).in_(action.names))
            if set(action.names) != {provider.name for provider in providers}:
                msg = "Policy providers must exist in the catalog"
                raise InvalidPolicyError(msg)
        policies = await self.for_workspace(self.workspace_id)
        if self.enabled and sum(policy.enabled and policy.id != self.id for policy in policies) >= MAX_WORKSPACE_POLICIES:
            msg = "A workspace may contain at most 100 active policies"
            raise InvalidPolicyError(msg)

    def entry(self) -> PolicyEntry:
        return PolicyEntry(id=self.id, workspace_id=self.workspace_id, name=self.name, priority=self.priority, definition=self.definition)


class InvalidPolicyError(ValueError):
    pass


class PolicyCreate(RecordCreate[Policy]):
    name: str = Field(min_length=1, max_length=200, description="Display name for the workspace policy")
    enabled: bool = Field(default=True, description="Whether gateways apply this policy after receiving the updated configuration")
    priority: int = Field(default=100, ge=0, le=10000, description="Lower numbers run first; policy ID breaks ties. All matching restrictions apply")
    definition: PolicyDefinition = Field(description="Inference key target, boolean CEL condition, and typed action. Budget actions are placeholders")

    @field_validator("definition")
    @classmethod
    def valid_condition(cls, definition: PolicyDefinition) -> PolicyDefinition:
        compile_condition(definition.condition)
        return definition


class PolicyUpdate(RecordUpdate[Policy]):
    name: str | None = Field(default=None, min_length=1, max_length=200, description="Replacement display name; omit to leave unchanged")
    enabled: bool | None = Field(default=None, description="Enable or disable this policy; omit to leave unchanged")
    priority: int | None = Field(default=None, ge=0, le=10000, description="Replacement priority, with lower numbers first; omit to leave unchanged")
    definition: PolicyDefinition | None = Field(
        default=None, description="Replace the complete target, CEL condition, and action; omit to leave unchanged"
    )

    @model_validator(mode="after")
    def nonnull_changes(self) -> Self:
        if any(getattr(self, field) is None for field in self.model_fields_set):
            msg = "Policy fields cannot be null"
            raise ValueError(msg)
        if self.definition is not None:
            compile_condition(self.definition.condition)
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
