from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from contract.model_types import MODALITIES, Capability, Modality, ParameterSupport
from contract.money import UsdRate
from contract.policies import PolicyEntry, RuleEntry
from contract.secrets import SecretRef


class KeyEntry(BaseModel):
    """An active inference key included in a policy bundle.

    The bundle contains a token hash for authorization and a key ID for usage attribution, never
    the caller's secret token.
    """

    model_config = ConfigDict(frozen=True)

    key_id: str = Field(min_length=1, max_length=255)
    org_id: UUID
    workspace_id: UUID  # the workspace the key was created in, stamped onto usage events
    user_id: UUID
    token_hash: str  # sha256 hex of the caller's bearer, the lookup key
    expires_at: datetime | None = None


class ProviderEntry(BaseModel):
    """An upstream LLM provider endpoint and its supported request parameters."""

    model_config = ConfigDict(frozen=True)

    provider_id: str
    kind: str
    base_url: HttpUrl
    param_aliases: dict[str, str] = Field(default_factory=dict)  # canonical param -> this provider's spelling
    accepted_params: list[str] | None = None  # params known accepted beyond the core; consulted when params_closed
    params_closed: bool = False  # True for the few providers whose schema rejects unknown params (3 of 22 in taxonomy)


class ModelEntry(BaseModel):
    """A routable model: the caller-facing id plus how to reach and bill it."""

    model_config = ConfigDict(frozen=True)

    model_id: str  # what the caller asks for
    provider_id: str
    upstream_model: str  # what the provider is sent
    input_price_per_mtok: UsdRate  # USD per million input tokens
    output_price_per_mtok: UsdRate  # USD per million output tokens
    cache_read_price_per_mtok: UsdRate  # USD per million cache-read input tokens
    cache_write_price_per_mtok: UsdRate  # USD per million cache-write input tokens
    context_window: int
    max_output_tokens: int | None = None  # completion cap; requests are clamped to it, distinct from context_window
    input_modalities: list[Modality] = Field(min_length=1, max_length=len(MODALITIES))
    output_modalities: list[Modality] = Field(min_length=1, max_length=len(MODALITIES))
    capabilities: list[Capability]
    parameter_support: dict[str, ParameterSupport] = Field(default_factory=dict)
    egress_kind: str | None = None


class CredentialEntry(BaseModel):
    """A provider credential reference, priority, and version included in a policy bundle.

    The secret value is not included. A version change tells data planes to refresh their cached value.
    """

    model_config = ConfigDict(frozen=True)

    ref: SecretRef
    priority: int  # lower is tried first, ties break by the ref's name
    version: int


class Catalog(BaseModel):
    """Everything routable in one org: providers, the models that point at them, and the credentials
    they are reached with."""

    model_config = ConfigDict(frozen=True)

    providers: list[ProviderEntry]
    models: list[ModelEntry]
    credentials: list[CredentialEntry] = Field(default_factory=list)


class BundleV1(BaseModel):
    """A complete, versioned policy snapshot for one organization's model traffic."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    bundle_id: UUID
    org_id: UUID
    issued_at: datetime
    keys: list[KeyEntry]
    catalog: Catalog
    rules: tuple[RuleEntry, ...]
    policies: tuple[PolicyEntry, ...]


class BundleManifestEntry(BaseModel):
    """The immutable identity of one organization bundle available to a data plane."""

    model_config = ConfigDict(frozen=True)

    org_id: UUID
    bundle_id: UUID


class BundleManifest(BaseModel):
    """The complete set of organization bundles one data plane may serve."""

    model_config = ConfigDict(frozen=True)

    bundles: list[BundleManifestEntry]
