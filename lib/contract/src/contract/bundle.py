from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, WrapSerializer, model_validator

from contract.model_types import (
    MODALITIES,
    AdapterKind,
    AuthenticationSource,
    Capability,
    Modality,
    ModelName,
    ParameterSupport,
    PrincipalType,
    ProviderName,
    TokenLimit,
)
from contract.money import UsdRate
from contract.policies import PolicyEntry
from contract.secrets import SecretRef


def _freeze_mapping[K, V](mapping: Mapping[K, V]) -> Mapping[K, V]:
    return MappingProxyType(dict(mapping))


class _BundleModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)


class KeyEntry(_BundleModel):
    """An active inference key included in a policy bundle.

    The bundle contains a token hash for authorization and a key ID for usage attribution, never
    the caller's secret token.
    """

    key_id: str = Field(min_length=1, max_length=255)
    org_id: UUID
    workspace_id: UUID  # the workspace the key was created in, stamped onto usage events
    user_id: UUID
    token_hash: str  # sha256 hex of the caller's bearer, the lookup key
    authentication_source: AuthenticationSource
    authentication_label: str = Field(min_length=1, max_length=200)
    principal_label: str = Field(min_length=1, max_length=320)
    principal_type: PrincipalType
    workspace_label: str = Field(min_length=1, max_length=200)
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid_principal_type(self) -> KeyEntry:
        valid = self.principal_type == "local" if self.authentication_source == "local" else self.principal_type in {"human", "service_account"}
        if not valid:
            message = "principal_type must match authentication_source"
            raise ValueError(message)
        return self


class ProviderEntry(_BundleModel):
    """An upstream LLM provider endpoint and its supported request parameters."""

    provider_id: ProviderName
    kind: AdapterKind
    base_url: HttpUrl
    param_aliases: Annotated[
        Mapping[str, str], Field(max_length=256), AfterValidator(_freeze_mapping), WrapSerializer(lambda mapping, handler: handler(dict(mapping)))
    ] = Field(default_factory=dict)  # canonical param -> this provider's spelling
    accepted_params: tuple[str, ...] | None = Field(
        default=None, max_length=256
    )  # params known accepted beyond the core; consulted when params_closed
    params_closed: bool = False  # True for the few providers whose schema rejects unknown params (3 of 22 in taxonomy)


class ModelEntry(_BundleModel):
    """A routable model: the caller-facing id plus how to reach and bill it."""

    model_id: ModelName  # what the caller asks for
    provider_id: ProviderName
    upstream_model: ModelName  # what the provider is sent
    input_price_per_mtok: UsdRate  # USD per million input tokens
    output_price_per_mtok: UsdRate  # USD per million output tokens
    cache_read_price_per_mtok: UsdRate  # USD per million cache-read input tokens
    cache_write_price_per_mtok: UsdRate  # USD per million cache-write input tokens
    context_window: TokenLimit
    max_output_tokens: TokenLimit | None = None  # completion cap; requests are clamped to it, distinct from context_window
    input_modalities: tuple[Modality, ...] = Field(min_length=1, max_length=len(MODALITIES))
    output_modalities: tuple[Modality, ...] = Field(min_length=1, max_length=len(MODALITIES))
    capabilities: tuple[Capability, ...] = Field(max_length=4)
    parameter_support: Annotated[
        Mapping[str, ParameterSupport],
        Field(max_length=128),
        AfterValidator(_freeze_mapping),
        WrapSerializer(lambda mapping, handler: handler(dict(mapping))),
    ] = Field(default_factory=dict)
    egress_kind: AdapterKind | None = None


class CredentialEntry(_BundleModel):
    """A provider credential reference, priority, and version included in a policy bundle.

    The secret value is not included. A version change tells data planes to refresh their cached value.
    """

    ref: SecretRef
    priority: int  # lower is tried first, ties break by the ref's name
    version: int


class Catalog(_BundleModel):
    """Everything routable in one org: providers, the models that point at them, and the credentials
    they are reached with."""

    providers: tuple[ProviderEntry, ...]
    models: tuple[ModelEntry, ...]
    credentials: tuple[CredentialEntry, ...] = ()


class BundleV1(_BundleModel):
    """A complete, versioned policy snapshot for one organization's model traffic."""

    schema_version: Literal[1] = 1
    bundle_id: UUID
    org_id: UUID
    issued_at: AwareDatetime
    keys: tuple[KeyEntry, ...]
    catalog: Catalog
    policies: tuple[PolicyEntry, ...]


class BundleManifestEntry(_BundleModel):
    """The immutable identity of one organization bundle available to a data plane."""

    org_id: UUID
    bundle_id: UUID


class BundleManifest(_BundleModel):
    """The complete set of organization bundles one data plane may serve."""

    bundles: tuple[BundleManifestEntry, ...]
