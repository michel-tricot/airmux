from __future__ import annotations

from decimal import Decimal
from functools import cache
from typing import Annotated, Literal, Self
from uuid import UUID

from cel_expr_python import cel
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PolicyName = Annotated[str, Field(min_length=1, max_length=200)]
PolicyIdentifier = Annotated[str, Field(min_length=1, max_length=255)]
FallbackReason = Literal["rate_limited", "upstream_unavailable", "timeout"]
MAX_WORKSPACE_POLICIES = 100
MAX_CONDITION_LENGTH = 2048


@cache
def condition_environment() -> cel.Env:
    return cel.NewEnv(
        config=cel.NewEnvConfigFromYaml("stdlib:\n  exclude_macros: [all, exists, exists_one, map, filter]\n"),
        variables={"request_model": cel.Type.STRING, "request_stream": cel.Type.BOOL, "key_id": cel.Type.STRING, "workspace_id": cel.Type.STRING},
    )


def compile_condition(condition: str) -> cel.Expression:
    if not 1 <= len(condition) <= MAX_CONDITION_LENGTH:
        msg = "Policy conditions must contain between 1 and 2048 characters"
        raise ValueError(msg)
    try:
        expression = condition_environment().compile(condition)
    except (ValueError, RuntimeError) as error:
        msg = f"Invalid policy condition: {error}"
        raise ValueError(msg) from error
    if expression.return_type() != cel.Type.BOOL:
        msg = "Policy conditions must return a boolean"
        raise ValueError(msg)
    return expression


class _PolicyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class AllKeys(_PolicyModel):
    kind: Literal["all_keys"]


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


PolicyTarget = Annotated[AllKeys | SelectedKeys, Field(discriminator="kind")]


class RequireByok(_PolicyModel):
    kind: Literal["byok"]


class AllowedModels(_PolicyModel):
    kind: Literal["models"]
    names: tuple[PolicyIdentifier, ...] = Field(min_length=1, max_length=1000)


class AllowedProviders(_PolicyModel):
    kind: Literal["providers"]
    names: tuple[PolicyIdentifier, ...] = Field(min_length=1, max_length=1000)


class DenyRequest(_PolicyModel):
    kind: Literal["deny"]
    message: PolicyName


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


class BudgetPlaceholder(_PolicyModel):
    kind: Literal["budget"]
    enforcement: Literal["placeholder"]
    period: Literal["day", "month"]
    amount_usd: Decimal = Field(gt=0, max_digits=16, decimal_places=6)
    sharing: Literal["shared", "per_key"]


PolicyAction = Annotated[RequireByok | AllowedModels | AllowedProviders | DenyRequest | Fallback | BudgetPlaceholder, Field(discriminator="kind")]


class PolicyDefinition(_PolicyModel):
    target: PolicyTarget
    condition: str = Field(min_length=1, max_length=2048)
    action: PolicyAction


class PolicyEntry(_PolicyModel):
    id: UUID
    workspace_id: UUID
    name: PolicyName
    priority: int = Field(ge=0, le=10000)
    definition: PolicyDefinition
