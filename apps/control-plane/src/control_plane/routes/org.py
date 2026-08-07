from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlmodel import col

from control_plane.authz import Scope
from control_plane.compiler import UnknownOrgError, compile_and_store
from control_plane.deps import MgmtDep, OrgDep, require
from control_plane.models import ApiKey, Bundle, DataPlaneInstance, Org, SsoConnection, UsageEvent
from control_plane.models.api_key import ApiKeyOut, KeyOut, KeyRevokedOut
from control_plane.models.bundle import BundleOut, CompileOut
from control_plane.models.data_plane_instance import DataPlaneInstanceOut
from control_plane.models.sso_connection import SsoConnectionIn, SsoConnectionOut
from control_plane.models.usage_event import UsageEventOut
from control_plane.schemas import DeletedOut, Envelope
from control_plane.tokens import mint_inference_key

router = APIRouter(prefix="/org")


@router.post("/keys", tags=["API Keys"], dependencies=[require(Scope.keys_write)])
async def create_key(org: OrgDep, claims: MgmtDep) -> Envelope[KeyOut]:
    if await Org.get(org) is None:
        raise HTTPException(status_code=404)
    key_id, token = await mint_inference_key(org, claims.user_id)
    return Envelope(data=KeyOut(key_id=key_id, token=token))


@router.delete("/keys/{key_id}", tags=["API Keys"], dependencies=[require(Scope.keys_write)])
async def revoke_key(org: OrgDep, key_id: str) -> Envelope[KeyRevokedOut]:
    key = await ApiKey.owned_by(org, key_id)
    key.disabled = True
    return Envelope(data=KeyRevokedOut(key_id=key_id, status="revoked"))


@router.post("/bundles/compile", tags=["Bundles"], dependencies=[require(Scope.bundles_write)])
async def compile_endpoint(org: OrgDep, request: Request) -> Envelope[CompileOut]:
    settings = request.app.state.settings
    now = datetime.now(tz=UTC)
    bundle_id = uuid4()
    try:
        version = await compile_and_store(org, bundle_id, now, settings.bundle.staleness_bound, settings.bundle.signing_key)
    except UnknownOrgError as e:
        raise HTTPException(status_code=404) from e
    return Envelope(data=CompileOut(bundle_id=str(bundle_id), version=version))


@router.get("/keys", tags=["API Keys"], dependencies=[require(Scope.keys_read)])
async def list_keys(org: OrgDep) -> Envelope[list[ApiKeyOut]]:
    return Envelope(data=[ApiKeyOut.model_validate(r) for r in await ApiKey.find(ApiKey.org_id == org, order_by=col(ApiKey.id))])


@router.get("/bundles", tags=["Bundles"], dependencies=[require(Scope.bundles_read)])
async def list_bundles(org: OrgDep) -> Envelope[list[BundleOut]]:
    rows = await Bundle.find(Bundle.org_id == org, order_by=col(Bundle.version))
    return Envelope(data=[BundleOut.model_validate(r) for r in rows])


@router.get("/instances", tags=["Instances"], dependencies=[require(Scope.instances_read)])
async def list_instances(org: OrgDep, include_offline: bool = False) -> Envelope[list[DataPlaneInstanceOut]]:
    """Data planes serving this org; offline ones are kept as history and shown only with include_offline."""
    now = datetime.now(tz=UTC)
    rows = await DataPlaneInstance.find(DataPlaneInstance.org_id == org, order_by=col(DataPlaneInstance.last_seen).desc())
    out = [DataPlaneInstanceOut(**r.model_dump(), status=status) for r in rows if (status := r.status(now)) == "online" or include_offline]
    return Envelope(data=out)


@router.post("/sso-connections", tags=["SSO"], dependencies=[require(Scope.sso_write)])
async def create_sso_connection(org: OrgDep, body: SsoConnectionIn) -> Envelope[SsoConnectionOut]:
    """Register an OIDC issuer for the org; the issuer's discovery document is fetched once here
    and its endpoints cached, so misconfiguration surfaces now and logins never depend on it."""
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(body.issuer.rstrip("/") + "/.well-known/openid-configuration")
            resp.raise_for_status()
            doc = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(status_code=502, detail="issuer discovery failed") from e
    if doc.get("issuer") != body.issuer or not all(isinstance(doc.get(k), str) for k in ("authorization_endpoint", "token_endpoint", "jwks_uri")):
        raise HTTPException(status_code=422, detail="discovery document does not match the issuer")
    row = await SsoConnection(
        id=f"sso-{uuid4().hex[:8]}",
        org_id=org,
        issuer=body.issuer,
        client_id=body.client_id,
        client_secret=body.client_secret,
        email_domains=[d.lower() for d in body.email_domains],
        jit=body.jit,
        authorization_endpoint=doc["authorization_endpoint"],
        token_endpoint=doc["token_endpoint"],
        jwks_uri=doc["jwks_uri"],
    ).save()
    return Envelope(data=SsoConnectionOut.model_validate(row))


@router.get("/sso-connections", tags=["SSO"], dependencies=[require(Scope.sso_read)])
async def list_sso_connections(org: OrgDep) -> Envelope[list[SsoConnectionOut]]:
    rows = await SsoConnection.find(SsoConnection.org_id == org, order_by=col(SsoConnection.id))
    return Envelope(data=[SsoConnectionOut.model_validate(r) for r in rows])


@router.delete("/sso-connections/{connection_id}", tags=["SSO"], dependencies=[require(Scope.sso_write)])
async def delete_sso_connection(org: OrgDep, connection_id: str) -> Envelope[DeletedOut[str]]:
    connection = await SsoConnection.owned_by(org, connection_id)
    await connection.delete()
    return Envelope(data=DeletedOut(id=connection_id, deleted_at=datetime.now(tz=UTC)))


@router.get("/events", tags=["Events"], dependencies=[require(Scope.events_read)])
async def list_events(org: OrgDep, after: datetime | None = None, limit: int = 50) -> Envelope[list[UsageEventOut]]:
    if after is not None:
        conditions = (UsageEvent.org_id == org, col(UsageEvent.occurred_at) > after)
        rows = await UsageEvent.find(*conditions, order_by=col(UsageEvent.occurred_at).asc(), limit=limit)
    else:
        rows = await UsageEvent.find(UsageEvent.org_id == org, order_by=col(UsageEvent.occurred_at).desc(), limit=limit)
    return Envelope(data=[UsageEventOut.model_validate(r) for r in rows])
