from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Self, override
from uuid import UUID

from pydantic import model_validator
from sqlalchemy import JSON, ForeignKeyConstraint, TypeDecorator, UniqueConstraint
from sqlmodel import Field, col, select

from contract.policies import AllowedModels, AllowedProviders, Fallback, RequestMatch, RuleDefinition, RuleEntry
from control_plane.db import current_session
from control_plane.models.audit import audited
from control_plane.models.common import Identified, NotOwnedError, OrgOwned, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordCreate, RecordOut, RecordUpdate
from control_plane.models.model import Model
from control_plane.models.provider import Provider
from control_plane.models.runtime_configuration import bundle_input

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect


class RuleDefinitionType(TypeDecorator[RuleDefinition]):
    impl = JSON
    cache_ok = True

    @override
    def process_bind_param(self, value: RuleDefinition | None, dialect: Dialect) -> dict[str, object] | None:
        return value.model_dump(mode="json") if value is not None else None

    @override
    def process_result_value(self, value: object, dialect: Dialect) -> RuleDefinition:
        return RuleDefinition.model_validate(value)


@audited
@bundle_input(scope="org", columns=("org_id", "workspace_id", "name", "definition"))
class Rule(Record, Identified, OrgOwned, Tombstonable, table=True):
    __table_args__: ClassVar = (
        ForeignKeyConstraint(["workspace_id", "org_id"], ["workspace.id", "workspace.org_id"]),
        UniqueConstraint("workspace_id", "name", name="rule_workspace_id_name_key"),
    )

    org_id: UUID = Field(foreign_key="org.id")
    workspace_id: UUID
    name: str = Field(min_length=1, max_length=200)
    definition: RuleDefinition = Field(sa_type=RuleDefinitionType, nullable=False)

    api_readonly: ClassVar[frozenset[str]] = frozenset({"workspace_id"})

    @classmethod
    async def in_workspace(cls, org_id: UUID, workspace_id: UUID, rule_id: UUID) -> Self:
        rule = await cls.owned_by(org_id, rule_id)
        if rule.workspace_id != workspace_id:
            raise NotOwnedError
        return rule

    @classmethod
    async def for_workspace(cls, workspace_id: UUID) -> list[Self]:
        return await cls.find(cls.workspace_id == workspace_id, order_by=(col(cls.name), col(cls.id)))

    @override
    async def save(self) -> Self:
        await self._lock_workspace()
        await self._validate_configuration()
        return await super().save()

    @override
    async def delete(self) -> None:
        from control_plane.models.policy import Policy  # noqa: PLC0415 rules are referenced by policies

        await self._lock_workspace()
        policies = await Policy.for_workspace(self.workspace_id)
        if any(self.id in policy.definition.rule_ids for policy in policies):
            msg = "Rule is used by one or more policies"
            raise RuleInUseError(msg)
        await super().delete()

    async def _lock_workspace(self) -> None:
        from control_plane.models.workspace import Workspace  # noqa: PLC0415 workspace deletion also depends on Rule

        await current_session().execute(select(Workspace.id).where(col(Workspace.id) == self.workspace_id).with_for_update())

    async def _validate_configuration(self) -> None:
        match = self.definition.match
        action = self.definition.action
        matched_models = set(match.models) if isinstance(match, RequestMatch) else set()
        action_models = set(action.names) if isinstance(action, AllowedModels) else set(action.models) if isinstance(action, Fallback) else set()
        model_names = matched_models | action_models
        if model_names:
            models = await Model.find(col(Model.name).in_(model_names))
            if model_names != {model.name for model in models}:
                msg = "Rule models must exist in the catalog"
                raise InvalidRuleError(msg)
        if isinstance(action, AllowedProviders):
            provider_names = set(action.names)
            providers = await Provider.find(col(Provider.name).in_(provider_names))
            if provider_names != {provider.name for provider in providers}:
                msg = "Rule providers must exist in the catalog"
                raise InvalidRuleError(msg)

    def entry(self) -> RuleEntry:
        return RuleEntry(id=self.id, workspace_id=self.workspace_id, name=self.name, definition=self.definition)


class InvalidRuleError(ValueError):
    pass


class RuleInUseError(ValueError):
    pass


class RuleCreate(RecordCreate[Rule]):
    name: str = Field(min_length=1, max_length=200, description="Display name for the reusable workspace rule")
    definition: RuleDefinition = Field(description="Request match and action shared by every policy that references this rule")


class RuleUpdate(RecordUpdate[Rule]):
    name: str | None = Field(default=None, min_length=1, max_length=200, description="Replacement display name; omit to leave unchanged")
    definition: RuleDefinition | None = Field(default=None, description="Replacement request match and action; omit to leave unchanged")

    @model_validator(mode="after")
    def nonnull_changes(self) -> Self:
        if any(getattr(self, field) is None for field in self.model_fields_set):
            msg = "Rule fields cannot be null"
            raise ValueError(msg)
        return self


class RuleOut(RecordOut[Rule]):
    id: UUID
    org_id: UUID
    workspace_id: UUID
    name: str
    definition: RuleDefinition
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
