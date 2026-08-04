from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlmodel import col, select

from contract import canonical_json, mint_api_token, private_key_from_b64, sign_bundle
from control_plane.compiler import UnknownOrgError, compile_bundle
from control_plane.deps import SessionDep, require_admin
from control_plane.models import ApiKey, Bundle, Model, Org, Provider, UsageEvent

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

ALLOWED_CREDENTIAL_SCHEMES = ("env:", "file:")
SIGNING_KEY_ID = "k1"


class OrgIn(BaseModel):
    id: str = Field(description="Org id, e.g. org-dev")
    name: str = Field("", description="Display name, defaults to the id")


class KeyIn(BaseModel):
    org_id: str = Field(description="Org the key belongs to")
    allowed_models: list[str] = Field(default=["*"], description="Model ids this key may call, * for all")


class ProviderIn(BaseModel):
    org_id: str = Field(description="Org the provider belongs to")
    provider_id: str = Field(description="Provider id, e.g. openai")
    kind: Literal["openai_compatible", "anthropic"] = Field("openai_compatible", description="Adapter kind")
    base_url: str = Field(description="OpenAI-compatible endpoint, e.g. https://api.groq.com/openai/v1")
    credential_ref: str = Field(description="env: or file: reference resolved by the data plane, never a raw secret")

    @field_validator("credential_ref")
    @classmethod
    def credential_ref_is_a_reference(cls, v: str) -> str:
        if not v.startswith(ALLOWED_CREDENTIAL_SCHEMES):
            msg = "credential_ref must be an env: or file: reference resolved by the data plane, never a raw secret"
            raise ValueError(msg)
        return v


class ModelIn(BaseModel):
    org_id: str = Field(description="Org the model belongs to")
    model_id: str = Field(description="Caller-facing model id")
    provider_id: str = Field(description="Provider id the model routes to")
    upstream_model: str = Field("", description="Model name sent to the provider, lets model_id be an alias; defaults to model_id")
    input_price_per_mtok: float = Field(0.0, description="USD per million input tokens")
    output_price_per_mtok: float = Field(0.0, description="USD per million output tokens")
    context_window: int = Field(128000, description="Context window in tokens")
    max_output_tokens: int | None = Field(None, description="Max completion tokens; requests are clamped to it")
    capabilities: list[str] = Field(default=["streaming", "tools"], description="Capabilities, comma separated")


class CompileIn(BaseModel):
    org_id: str = Field(description="Org to compile the bundle for")


class OrgOut(BaseModel):
    id: str


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


@router.post("/orgs")
async def create_org(body: OrgIn, session: SessionDep) -> OrgOut:
    if await session.get(Org, body.id) is not None:
        raise HTTPException(status_code=409)
    session.add(Org(id=body.id, name=body.name or body.id, created_at=datetime.now(tz=UTC)))
    await session.commit()
    return OrgOut(id=body.id)


@router.post("/keys")
async def create_key(body: KeyIn, session: SessionDep, request: Request) -> KeyOut:
    if await session.get(Org, body.org_id) is None:
        raise HTTPException(status_code=404)
    now = datetime.now(tz=UTC)
    key_id = f"k-{uuid4().hex[:8]}"
    session.add(ApiKey(id=key_id, org_id=body.org_id, allowed_models=body.allowed_models, disabled=False, created_at=now))
    await session.commit()
    settings = request.app.state.settings
    token = mint_api_token(key_id, body.org_id, private_key_from_b64(settings.auth.token_signing_key), now)
    return KeyOut(key_id=key_id, token=token)


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: str, session: SessionDep) -> KeyRevokedOut:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=404)
    key.disabled = True
    session.add(key)
    await session.commit()
    return KeyRevokedOut(key_id=key_id, status="revoked")


@router.post("/providers")
async def create_provider(body: ProviderIn, session: SessionDep) -> ProviderOut:
    """Create or update: reapplying a bootstrap spec converges the catalog."""
    if await session.get(Org, body.org_id) is None:
        raise HTTPException(status_code=404)
    provider = await session.get(Provider, body.provider_id)
    if provider is None:
        provider = Provider(id=body.provider_id, org_id=body.org_id, kind=body.kind, base_url=body.base_url, credential_ref=body.credential_ref)
    else:
        provider.kind = body.kind
        provider.base_url = body.base_url
        provider.credential_ref = body.credential_ref
    session.add(provider)
    await session.commit()
    return ProviderOut(provider_id=body.provider_id)


@router.post("/models")
async def create_model(body: ModelIn, session: SessionDep) -> ModelOut:
    """Create or update: reapplying a bootstrap spec converges the catalog."""
    if await session.get(Provider, body.provider_id) is None:
        raise HTTPException(status_code=404)
    model = await session.get(Model, body.model_id)
    if model is None:
        model = Model(
            id=body.model_id,
            org_id=body.org_id,
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
    session.add(model)
    await session.commit()
    return ModelOut(model_id=body.model_id)


@router.post("/bundles/compile")
async def compile_endpoint(body: CompileIn, session: SessionDep, request: Request) -> CompileOut:
    settings = request.app.state.settings
    now = datetime.now(tz=UTC)
    bundle_id = uuid4()
    try:
        bundle = await compile_bundle(session, body.org_id, bundle_id, now, settings.bundle.staleness_bound)
    except UnknownOrgError as e:
        raise HTTPException(status_code=404) from e
    signed = sign_bundle(bundle, private_key_from_b64(settings.bundle.signing_key), SIGNING_KEY_ID)
    version = (await session.execute(select(func.max(Bundle.version)).where(Bundle.org_id == body.org_id))).scalar() or 0
    session.add(
        Bundle(
            id=bundle_id,
            org_id=body.org_id,
            version=version + 1,
            issued_at=now,
            expires_at=bundle.expires_at,
            payload=canonical_json(bundle),
            signature=signed.signature,
            signing_key_id=signed.signing_key_id,
        )
    )
    await session.commit()
    return CompileOut(bundle_id=str(bundle_id), version=version + 1)


class BundleOut(BaseModel):
    id: UUID
    org_id: str
    version: int
    issued_at: datetime
    expires_at: datetime
    signing_key_id: str


@router.get("/orgs")
async def list_orgs(session: SessionDep) -> list[Org]:
    return list((await session.execute(select(Org).order_by(Org.id))).scalars().all())


@router.get("/keys")
async def list_keys(session: SessionDep, org_id: str | None = None) -> list[ApiKey]:
    query = select(ApiKey).order_by(ApiKey.id)
    if org_id:
        query = query.where(ApiKey.org_id == org_id)
    return list((await session.execute(query)).scalars().all())


@router.get("/providers")
async def list_providers(session: SessionDep, org_id: str | None = None) -> list[Provider]:
    query = select(Provider).order_by(Provider.id)
    if org_id:
        query = query.where(Provider.org_id == org_id)
    return list((await session.execute(query)).scalars().all())


@router.get("/models")
async def list_models(session: SessionDep, org_id: str | None = None) -> list[Model]:
    query = select(Model).order_by(Model.id)
    if org_id:
        query = query.where(Model.org_id == org_id)
    return list((await session.execute(query)).scalars().all())


@router.get("/events")
async def list_events(session: SessionDep, org_id: str | None = None, after: datetime | None = None, limit: int = 50) -> list[UsageEvent]:
    query = select(UsageEvent)
    if org_id:
        query = query.where(UsageEvent.org_id == org_id)
    if after is not None:
        query = query.where(col(UsageEvent.occurred_at) > after).order_by(col(UsageEvent.occurred_at).asc())
    else:
        query = query.order_by(col(UsageEvent.occurred_at).desc())
    return list((await session.execute(query.limit(limit))).scalars().all())


@router.get("/bundles")
async def list_bundles(session: SessionDep, org_id: str | None = None) -> list[BundleOut]:
    query = select(Bundle).order_by(col(Bundle.org_id), col(Bundle.version))
    if org_id:
        query = query.where(Bundle.org_id == org_id)
    rows = (await session.execute(query)).scalars().all()
    return [BundleOut(**r.model_dump(exclude={"payload", "signature"})) for r in rows]
