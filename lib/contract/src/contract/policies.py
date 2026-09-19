from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contract.events import CredentialScope
from contract.model_types import RequestCapability
from contract.money import UsdAmount, UsdRate

PolicyName = Annotated[str, Field(min_length=1, max_length=200)]
PolicyIdentifier = Annotated[str, Field(min_length=1, max_length=255)]
FallbackReason = Literal["rate_limited", "upstream_unavailable", "timeout"]
BudgetPeriod = Literal["day", "month"]
MAX_WORKSPACE_RULES = 100


class _PolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False, json_schema_serialization_defaults_required=True)


class WorkspaceTarget(_PolicyModel):
    kind: Literal["workspace"]


class SelectedKeys(_PolicyModel):
    kind: Literal["selected_keys"]
    key_ids: tuple[PolicyIdentifier, ...] = Field(min_length=1, max_length=1000)

    @field_validator("key_ids")
    @classmethod
    def unique_keys(cls, keys: tuple[str, ...]) -> tuple[str, ...]:
        if len(keys) != len(set(keys)):
            msg = "Selected inference keys must be unique"
            raise ValueError(msg)
        return keys


class SelectedUsers(_PolicyModel):
    kind: Literal["selected_users"]
    user_ids: tuple[UUID, ...] = Field(min_length=1, max_length=1000)

    @field_validator("user_ids")
    @classmethod
    def unique_users(cls, user_ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(user_ids) != len(set(user_ids)):
            msg = "Selected users must be unique"
            raise ValueError(msg)
        return user_ids


PolicyTarget = Annotated[WorkspaceTarget | SelectedUsers | SelectedKeys, Field(discriminator="kind")]


class AllRequests(_PolicyModel):
    kind: Literal["all_requests"]


class RequestMatch(_PolicyModel):
    kind: Literal["request"]
    models: tuple[PolicyIdentifier, ...] = Field(default=(), max_length=1000)
    stream: bool | None = Field(default=None, strict=True)
    capabilities: tuple[RequestCapability, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def valid_criteria(self) -> Self:
        if not self.models and self.stream is None and not self.capabilities:
            msg = "A request match must contain at least one criterion"
            raise ValueError(msg)
        if len(self.models) != len(set(self.models)) or len(self.capabilities) != len(set(self.capabilities)):
            msg = "Request match models and capabilities must be unique"
            raise ValueError(msg)
        return self


PolicyMatch = Annotated[AllRequests | RequestMatch, Field(discriminator="kind")]


class AllowedModels(_PolicyModel):
    kind: Literal["models"]
    names: tuple[PolicyIdentifier, ...] = Field(min_length=1, max_length=1000)


class AllowedProviders(_PolicyModel):
    kind: Literal["providers"]
    names: tuple[PolicyIdentifier, ...] = Field(min_length=1, max_length=1000)


class DenyRequest(_PolicyModel):
    kind: Literal["deny"]
    message: PolicyName


class StrictParameters(_PolicyModel):
    kind: Literal["strict_parameters"]


class PriceLimit(_PolicyModel):
    kind: Literal["price_limit"]
    max_input_price_per_mtok: UsdRate
    max_output_price_per_mtok: UsdRate


class RequestLimits(_PolicyModel):
    kind: Literal["request_limits"]
    max_output_tokens: int = Field(ge=1)


class CredentialAccess(_PolicyModel):
    kind: Literal["credential_access"]
    scopes: tuple[CredentialScope, ...] = Field(min_length=1, max_length=3)

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, scopes: tuple[CredentialScope, ...]) -> tuple[CredentialScope, ...]:
        if len(scopes) != len(set(scopes)):
            msg = "Credential scopes must be unique"
            raise ValueError(msg)
        return scopes


class Budget(_PolicyModel):
    kind: Literal["budget"]
    amount_usd: UsdAmount = Field(gt=0)
    period: BudgetPeriod
    sharing: Literal["shared", "per_key"]


class Fallback(_PolicyModel):
    kind: Literal["fallback"]
    models: tuple[PolicyIdentifier, ...] = Field(min_length=1, max_length=4)
    on: tuple[FallbackReason, ...] = Field(min_length=1, max_length=3)
    max_attempts: int = Field(ge=2, le=5)
    timeout_ms: int = Field(ge=100, le=120000)

    @model_validator(mode="after")
    def unique_routes(self) -> Self:
        if len(self.models) != len(set(self.models)) or len(self.on) != len(set(self.on)):
            msg = "Fallback models and failure reasons must be unique"
            raise ValueError(msg)
        return self


PolicyAction = Annotated[
    AllowedModels | AllowedProviders | DenyRequest | StrictParameters | PriceLimit | RequestLimits | CredentialAccess | Fallback | Budget,
    Field(discriminator="kind"),
]


class RuleDefinition(_PolicyModel):
    match: PolicyMatch
    action: PolicyAction


class PolicyDefinition(_PolicyModel):
    target: PolicyTarget
    rules: tuple[RuleDefinition, ...] = Field(
        min_length=1,
        max_length=MAX_WORKSPACE_RULES,
        description="Unordered inline rule definitions; a policy may contain at most one fallback rule",
    )

    @field_validator("rules")
    @classmethod
    def valid_rules(cls, rules: tuple[RuleDefinition, ...]) -> tuple[RuleDefinition, ...]:
        if len(set(rules)) != len(rules):
            msg = "Policy rules must be unique"
            raise ValueError(msg)
        if sum(isinstance(rule.action, Fallback) for rule in rules) > 1:
            msg = "A policy may contain at most one fallback rule"
            raise ValueError(msg)
        return tuple(sorted(rules, key=lambda rule: rule.model_dump_json()))


class PolicyEntry(_PolicyModel):
    id: UUID
    workspace_id: UUID
    name: PolicyName
    priority: int = Field(ge=0, le=10000)
    definition: PolicyDefinition
