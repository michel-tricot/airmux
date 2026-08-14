from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from contract.secrets import SecretRef


class KeyEntry(BaseModel):
    """An API key as the data plane sees it: enough to authorize with zero I/O.

    The caller's bearer is an opaque secret; the data plane hashes it (see
    credentials.py) and looks the hash up here. Absence is invalidity, so
    revocation is simply dropping out of the next bundle. key_id exists for
    event attribution only. The bundle carries hashes of live secrets and
    stays org-sensitive even though the hashes are not reversible.
    """

    model_config = ConfigDict(frozen=True)

    key_id: str
    org_id: UUID
    workspace_id: UUID  # the workspace the key was minted in, stamped onto usage events
    token_hash: str  # sha256 hex of the caller's bearer, the lookup key


class ProviderEntry(BaseModel):
    """An upstream LLM provider endpoint, plus its profile: declarative facts about what the
    provider accepts, so onboarding quirks is a bundle edit rather than an adapter branch.
    Profile fields are names, sets and flags, never predicates; a provider that needs a
    predicate needs an adapter."""

    model_config = ConfigDict(frozen=True)

    provider_id: str
    kind: Literal["openai_compatible", "anthropic"]  # selects the adapter
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
    input_price_per_mtok: float  # USD per million input tokens
    output_price_per_mtok: float  # USD per million output tokens
    cache_read_price_per_mtok: float  # USD per million cache-read input tokens
    cache_write_price_per_mtok: float  # USD per million cache-write input tokens
    context_window: int
    max_output_tokens: int | None = None  # completion cap; requests are clamped to it, distinct from context_window
    capabilities: list[str]  # "streaming", "tools", "vision"


class CredentialEntry(BaseModel):
    """One provider key the data plane may spend against, named but not carried.

    The ref says which secret; the data plane fetches the value from the store it is configured
    with. Nothing here is a secret and nothing here is a location, so a bundle at rest and a bundle
    on the wire are both safe to read.

    version is the cache key: a rotation keeps the ref and bumps this, so a data plane refetches
    within one poll rather than waiting out a TTL.
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
    credentials: list[CredentialEntry] = []


class BundleV1(BaseModel):
    """The complete policy snapshot one data plane needs to serve requests with no database.

    Compiled by the control plane as a pure function of database state, signed, and polled
    by the data plane. If a feature seems to need a DB read on the request path, the bundle
    is missing a field; add the field here instead.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    bundle_id: UUID
    org_id: UUID
    issued_at: datetime
    expires_at: datetime  # staleness bound: issued_at + STALENESS_BOUND, checked on every swap
    keys: list[KeyEntry]
    catalog: Catalog


class SignedBundle(BaseModel):
    """A BundleV1 as it crosses the wire and rests on disk.

    A bundle that fails verification is rejected and the previous one keeps serving.
    """

    model_config = ConfigDict(frozen=True)

    payload: BundleV1
    signature: str  # Ed25519 over canonical_json(payload), base64
    signing_key_id: str  # selects the public key the data plane verifies with
