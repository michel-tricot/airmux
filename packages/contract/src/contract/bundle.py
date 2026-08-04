from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl


class KeyEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    key_id: str
    key_hash: str
    org_id: str
    allowed_models: list[str]
    disabled: bool = False


class ProviderEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_id: str
    kind: Literal["openai_compatible", "anthropic"]
    base_url: HttpUrl
    credential_ref: str


class ModelEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    provider_id: str
    upstream_model: str
    input_price_per_mtok: float
    output_price_per_mtok: float
    context_window: int
    capabilities: list[str]


class Catalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    providers: list[ProviderEntry]
    models: list[ModelEntry]


class BundleV1(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    bundle_id: UUID
    org_id: str
    issued_at: datetime
    expires_at: datetime
    keys: list[KeyEntry]
    revocations: list[str]
    catalog: Catalog


class SignedBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    payload: str
    signature: str
    signing_key_id: str
