from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, HttpUrl


class KeyEntry(BaseModel):
    """An API key as the data plane sees it: enough to authorize with zero I/O.

    Authentication is the caller's signed JWT (see tokens.py), verified against the
    signing public key; this entry is then looked up by the token's key_id claim.
    A valid signature is not enough on its own: the key must exist here, be enabled,
    and not be revoked, so revocation wins over any token still in the wild.
    """

    model_config = ConfigDict(frozen=True)

    key_id: str
    org_id: str
    allowed_models: list[str]  # model_ids this key may call, ["*"] permitted
    disabled: bool = False


class ProviderEntry(BaseModel):
    """An upstream LLM provider endpoint."""

    model_config = ConfigDict(frozen=True)

    provider_id: str
    kind: Literal["openai_compatible", "anthropic"]  # selects the adapter
    base_url: HttpUrl
    credential_ref: str  # NOT a secret: a URI (env:VAR, file:/path) resolved locally by the data plane


class ModelEntry(BaseModel):
    """A routable model: the caller-facing id plus how to reach and bill it."""

    model_config = ConfigDict(frozen=True)

    model_id: str  # what the caller asks for
    provider_id: str
    upstream_model: str  # what the provider is sent
    input_price_per_mtok: float  # USD per million input tokens
    output_price_per_mtok: float  # USD per million output tokens
    context_window: int
    capabilities: list[str]  # "streaming", "tools", "vision"


class Catalog(BaseModel):
    """Everything routable in one org: providers and the models that point at them."""

    model_config = ConfigDict(frozen=True)

    providers: list[ProviderEntry]
    models: list[ModelEntry]


class BundleV1(BaseModel):
    """The complete policy snapshot one data plane needs to serve requests with no database.

    Compiled by the control plane as a pure function of database state, signed, and polled
    by the data plane. If a feature seems to need a DB read on the request path, the bundle
    is missing a field; add the field here instead.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    bundle_id: UUID
    org_id: str
    issued_at: datetime
    expires_at: datetime  # staleness bound: issued_at + STALENESS_BOUND, checked on every swap
    keys: list[KeyEntry]
    revocations: list[str]  # key_ids revoked since issue, rejected even if still in keys
    catalog: Catalog


class SignedBundle(BaseModel):
    """A BundleV1 as it crosses the wire and rests on disk.

    A bundle that fails verification is rejected and the previous one keeps serving.
    """

    model_config = ConfigDict(frozen=True)

    payload: BundleV1
    signature: str  # Ed25519 over canonical_json(payload), base64
    signing_key_id: str  # selects the public key the data plane verifies with
