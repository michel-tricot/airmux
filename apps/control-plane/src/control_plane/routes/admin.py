from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlmodel import select

from contract import canonical_json, mint_api_token, private_key_from_b64, sign_bundle
from control_plane.compiler import UnknownOrgError, compile_bundle
from control_plane.deps import SessionDep, require_admin
from control_plane.models import ApiKey, Bundle, Model, Org, Provider

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

ALLOWED_CREDENTIAL_SCHEMES = ("env:", "file:")
SIGNING_KEY_ID = "k1"


class OrgIn(BaseModel):
    id: str
    name: str = ""


class KeyIn(BaseModel):
    org_id: str
    allowed_models: list[str] = Field(default_factory=lambda: ["*"])


class ProviderIn(BaseModel):
    org_id: str
    provider_id: str
    kind: Literal["openai_compatible", "anthropic"]
    base_url: str
    credential_ref: str

    @field_validator("credential_ref")
    @classmethod
    def credential_ref_is_a_reference(cls, v: str) -> str:
        if not v.startswith(ALLOWED_CREDENTIAL_SCHEMES):
            msg = "credential_ref must be an env: or file: reference resolved by the data plane, never a raw secret"
            raise ValueError(msg)
        return v


class ModelIn(BaseModel):
    org_id: str
    model_id: str
    provider_id: str
    upstream_model: str = ""
    input_price_per_mtok: float = 0.0
    output_price_per_mtok: float = 0.0
    context_window: int = 128000
    capabilities: list[str] = Field(default_factory=lambda: ["streaming", "tools"])


class CompileIn(BaseModel):
    org_id: str


@router.post("/orgs")
async def create_org(body: OrgIn, session: SessionDep) -> dict[str, str]:
    if await session.get(Org, body.id) is not None:
        raise HTTPException(status_code=409)
    session.add(Org(id=body.id, name=body.name or body.id, created_at=datetime.now(tz=UTC)))
    await session.commit()
    return {"id": body.id}


@router.post("/keys")
async def create_key(body: KeyIn, session: SessionDep, request: Request) -> dict[str, str]:
    if await session.get(Org, body.org_id) is None:
        raise HTTPException(status_code=404)
    now = datetime.now(tz=UTC)
    key_id = f"k-{uuid4().hex[:8]}"
    session.add(ApiKey(id=key_id, org_id=body.org_id, allowed_models=body.allowed_models, disabled=False, created_at=now))
    await session.commit()
    settings = request.app.state.settings
    token = mint_api_token(key_id, body.org_id, private_key_from_b64(settings.auth.token_signing_key), now)
    return {"key_id": key_id, "token": token}


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: str, session: SessionDep) -> dict[str, str]:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=404)
    key.disabled = True
    session.add(key)
    await session.commit()
    return {"key_id": key_id, "status": "revoked"}


@router.post("/providers")
async def create_provider(body: ProviderIn, session: SessionDep) -> dict[str, str]:
    if await session.get(Org, body.org_id) is None:
        raise HTTPException(status_code=404)
    if await session.get(Provider, body.provider_id) is not None:
        raise HTTPException(status_code=409)
    session.add(Provider(id=body.provider_id, org_id=body.org_id, kind=body.kind, base_url=body.base_url, credential_ref=body.credential_ref))
    await session.commit()
    return {"provider_id": body.provider_id}


@router.post("/models")
async def create_model(body: ModelIn, session: SessionDep) -> dict[str, str]:
    if await session.get(Provider, body.provider_id) is None:
        raise HTTPException(status_code=404)
    if await session.get(Model, body.model_id) is not None:
        raise HTTPException(status_code=409)
    session.add(
        Model(
            id=body.model_id,
            org_id=body.org_id,
            provider_id=body.provider_id,
            upstream_model=body.upstream_model or body.model_id,
            input_price_per_mtok=body.input_price_per_mtok,
            output_price_per_mtok=body.output_price_per_mtok,
            context_window=body.context_window,
            capabilities=body.capabilities,
        )
    )
    await session.commit()
    return {"model_id": body.model_id}


@router.post("/bundles/compile")
async def compile_endpoint(body: CompileIn, session: SessionDep, request: Request) -> dict[str, str | int]:
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
    return {"bundle_id": str(bundle_id), "version": version + 1}


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


@router.get("/bundles")
async def list_bundles(session: SessionDep, org_id: str | None = None) -> list[BundleOut]:
    query = select(Bundle).order_by(Bundle.org_id, Bundle.version)
    if org_id:
        query = query.where(Bundle.org_id == org_id)
    rows = (await session.execute(query)).scalars().all()
    return [BundleOut(**r.model_dump(exclude={"payload", "signature"})) for r in rows]
