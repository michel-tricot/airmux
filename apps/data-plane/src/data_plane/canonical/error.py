from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field
from pydantic_core import core_schema


class GatewayErrorCode(StrEnum):
    bundle_unavailable = "bundle_unavailable"
    credential_backend_unavailable = "credential_backend_unavailable"
    credential_missing = "credential_missing"
    credential_unavailable = "credential_unavailable"
    cross_site_request = "cross_site_request"
    fallback_deadline_exceeded = "fallback_deadline_exceeded"
    invalid_dialect = "invalid_dialect"
    invalid_request = "invalid_request"
    invalid_token = "invalid_token"  # noqa: S105 gateway error code, not a secret
    invalid_upstream_response = "invalid_upstream_response"
    metering_capacity_exhausted = "metering_capacity_exhausted"
    missing_bearer_token = "missing_bearer_token"  # noqa: S105 gateway error code, not a secret
    missing_requested_with = "missing_requested_with"
    policy_denied = "policy_denied"
    provider_not_configured = "provider_not_configured"
    unknown_model = "unknown_model"
    unsupported_feature = "unsupported_feature"
    unsupported_input_modality = "unsupported_input_modality"
    upstream_error = "upstream_error"
    upstream_timeout = "upstream_timeout"
    upstream_unreachable = "upstream_unreachable"


type GatewayDenyCode = Literal[
    "unknown_model",
    "unsupported_input_modality",
    "unsupported_feature",
    "provider_not_configured",
    "credential_unavailable",
    "policy_denied",
]

PROVIDER_ERROR_CODE_MAX_LENGTH = 128


class ProviderErrorCode(str):
    def __new__(cls, value: str) -> Self:
        if not 1 <= len(value) <= PROVIDER_ERROR_CODE_MAX_LENGTH:
            message = "provider error code must contain between 1 and 128 characters"
            raise ValueError(message)
        return super().__new__(cls, value)

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: object, _handler: object) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(cls, core_schema.str_schema())


class CanonicalError(BaseModel):
    status: int
    code: GatewayErrorCode | ProviderErrorCode
    message: Annotated[str, Field(max_length=1024)]
