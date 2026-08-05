from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlmodel import col

from contract import mint_inference_token, private_key_from_b64
from control_plane.compiler import UnknownOrgError, compile_and_store
from control_plane.deps import OrgDep  # noqa: TC001 FastAPI resolves dependency annotations at runtime
from control_plane.models import ApiKey, Bundle, DataPlaneInstance, Model, Org, Provider, UsageEvent

router = APIRouter(prefix="/org")

ALLOWED_CREDENTIAL_SCHEMES = ("env:", "file:")
# A data plane is considered offline after three missed heartbeats; the row itself is never deleted.
INSTANCE_STALE_AFTER = timedelta(seconds=90)


class KeyIn(BaseModel):
    allowed_models: list[str] = Field(default=["*"], description="Model ids this key may call, * for all")


class ProviderIn(BaseModel):
    provider_id: str = Field(description="Provider id, e.g. openai")
    kind: Literal["openai_compatible", "anthropic"] = Field("openai_compatible", description="Adapter kind")
    base_url: str = Field(description="OpenAI-compatible endpoint, e.g. https://api.groq.com/openai/v1")
    credential_ref: str = Field(description="env: or file: reference resolved by the data plane, never a raw secret")
    cache_read_multiplier: float = Field(1.0, description="Input price factor for prompt-cache hits")
    cache_write_multiplier: float = Field(1.0, description="Input price factor for cache writes")

    @field_validator("credential_ref")
    @classmethod
    def credential_ref_is_a_reference(cls, v: str) -> str:
        if not v.startswith(ALLOWED_CREDENTIAL_SCHEMES):
            msg = "credential_ref must be an env: or file: reference resolved by the data plane, never a raw secret"
            raise ValueError(msg)
        return v


class ModelIn(BaseModel):
    model_id: str = Field(description="Caller-facing model id")
    provider_id: str = Field(description="Provider id the model routes to")
    upstream_model: str = Field("", description="Model name sent to the provider, lets model_id be an alias; defaults to model_id")
    input_price_per_mtok: float = Field(0.0, description="USD per million input tokens")
    output_price_per_mtok: float = Field(0.0, description="USD per million output tokens")
    context_window: int = Field(128000, description="Context window in tokens")
    max_output_tokens: int | None = Field(None, description="Max completion tokens; requests are clamped to it")
    capabilities: list[str] = Field(default=["streaming", "tools"], description="Capabilities, comma separated")


class KeyOut(BaseModel):
    key_id: str
    token: str


class KeyRevokedOut(BaseModel):
    key_id: str
    status: Literal["revoked"]


class ProviderOut(BaseModel):
    provider_id: str


class ModelOut(BaseModel):
    model_id: str


class CompileOut(BaseModel):
    bundle_id: str
    version: int


class BundleOut(BaseModel):
    id: UUID
    org_id: str
    version: int
    issued_at: datetime
    expires_at: datetime
    signing_key_id: str


class InstanceOut(BaseModel):
    instance_id: str
    org_id: str | None
    version: str
    bundle_id: UUID | None
    address: str | None
    status: Literal["online", "offline"]
    first_seen: datetime
    last_seen: datetime


@router.post("/keys")
async def create_key(org: OrgDep, body: KeyIn, request: Request) -> KeyOut:
    if await Org.get(org) is None:
        raise HTTPException(status_code=404)
    now = datetime.now(tz=UTC)
    key_id = f"k-{uuid4().hex[:8]}"
    await ApiKey(id=key_id, org_id=org, allowed_models=body.allowed_models, disabled=False).save()
    settings = request.app.state.settings
    token = mint_inference_token(key_id, org, private_key_from_b64(settings.auth.token_signing_key), now)
    return KeyOut(key_id=key_id, token=token)


@router.delete("/keys/{key_id}")
async def revoke_key(org: OrgDep, key_id: str) -> KeyRevokedOut:
    key = await ApiKey.owned_by(org, key_id)
    key.disabled = True
    return KeyRevokedOut(key_id=key_id, status="revoked")


@router.post("/providers")
async def create_provider(org: OrgDep, body: ProviderIn) -> ProviderOut:
    """Create or update: reapplying a bootstrap spec converges the catalog."""
    provider = await Provider.get(body.provider_id)
    if provider is not None and provider.org_id != org:
        raise HTTPException(status_code=409)
    if provider is None:
        provider = Provider(id=body.provider_id, org_id=org, kind=body.kind, base_url=body.base_url, credential_ref=body.credential_ref)
    else:
        provider.kind = body.kind
        provider.base_url = body.base_url
        provider.credential_ref = body.credential_ref
    provider.cache_read_multiplier = body.cache_read_multiplier
    provider.cache_write_multiplier = body.cache_write_multiplier
    await provider.save()
    return ProviderOut(provider_id=body.provider_id)


@router.post("/models")
async def create_model(org: OrgDep, body: ModelIn) -> ModelOut:
    """Create or update: reapplying a bootstrap spec converges the catalog."""
    provider = await Provider.get(body.provider_id)
    if provider is None or provider.org_id != org:
        raise HTTPException(status_code=404)
    model = await Model.get(body.model_id)
    if model is not None and model.org_id != org:
        raise HTTPException(status_code=409)
    if model is None:
        model = Model(
            id=body.model_id,
            org_id=org,
            provider_id=body.provider_id,
            upstream_model=body.upstream_model or body.model_id,
            input_price_per_mtok=body.input_price_per_mtok,
            output_price_per_mtok=body.output_price_per_mtok,
            context_window=body.context_window,
            max_output_tokens=body.max_output_tokens,
            capabilities=body.capabilities,
        )
    else:
        model.provider_id = body.provider_id
        model.upstream_model = body.upstream_model or body.model_id
        model.input_price_per_mtok = body.input_price_per_mtok
        model.output_price_per_mtok = body.output_price_per_mtok
        model.context_window = body.context_window
        model.max_output_tokens = body.max_output_tokens
        model.capabilities = body.capabilities
    await model.save()
    return ModelOut(model_id=body.model_id)


@router.post("/bundles/compile")
async def compile_endpoint(org: OrgDep, request: Request) -> CompileOut:
    settings = request.app.state.settings
    now = datetime.now(tz=UTC)
    bundle_id = uuid4()
    try:
        version = await compile_and_store(org, bundle_id, now, settings.bundle.staleness_bound, settings.bundle.signing_key)
    except UnknownOrgError as e:
        raise HTTPException(status_code=404) from e
    return CompileOut(bundle_id=str(bundle_id), version=version)


@router.get("/keys")
async def list_keys(org: OrgDep) -> list[ApiKey]:
    return await ApiKey.find(ApiKey.org_id == org, order_by=col(ApiKey.id))


@router.get("/providers")
async def list_providers(org: OrgDep) -> list[Provider]:
    return await Provider.find(Provider.org_id == org, order_by=col(Provider.id))


@router.get("/models")
async def list_models(org: OrgDep) -> list[Model]:
    return await Model.find(Model.org_id == org, order_by=col(Model.id))


@router.get("/bundles")
async def list_bundles(org: OrgDep) -> list[BundleOut]:
    rows = await Bundle.find(Bundle.org_id == org, order_by=col(Bundle.version))
    return [BundleOut(**r.model_dump(exclude={"payload", "signature"})) for r in rows]


@router.get("/instances")
async def list_instances(org: OrgDep, include_offline: bool = False) -> list[InstanceOut]:
    """Data planes serving this org; offline ones are kept as history and shown only with include_offline."""
    now = datetime.now(tz=UTC)
    rows = await DataPlaneInstance.find(DataPlaneInstance.org_id == org, order_by=col(DataPlaneInstance.last_seen).desc())
    out: list[InstanceOut] = []
    for r in rows:
        last_seen = r.last_seen if r.last_seen.tzinfo else r.last_seen.replace(tzinfo=UTC)
        status = "online" if now - last_seen < INSTANCE_STALE_AFTER else "offline"
        if status == "offline" and not include_offline:
            continue
        out.append(InstanceOut(**r.model_dump(), status=status))
    return out


@router.get("/events")
async def list_events(org: OrgDep, after: datetime | None = None, limit: int = 50) -> list[UsageEvent]:
    if after is not None:
        conditions = (UsageEvent.org_id == org, col(UsageEvent.occurred_at) > after)
        return await UsageEvent.find(*conditions, order_by=col(UsageEvent.occurred_at).asc(), limit=limit)
    return await UsageEvent.find(UsageEvent.org_id == org, order_by=col(UsageEvent.occurred_at).desc(), limit=limit)
