from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col

from control_plane.authz import Scope
from control_plane.deps import MgmtDep, instance_scope, require
from control_plane.keys import mint_management_key
from control_plane.models import DataPlaneInstance, ManagementKey, User
from control_plane.models.common.wire import Envelope
from control_plane.models.data_plane_instance import DataPlaneInstanceOut
from control_plane.models.management_key import ManagementKeyIn, ManagementKeyMintedOut, ManagementKeyOut, ManagementKeyRevokedOut

router = APIRouter(prefix="/instance", dependencies=[Depends(instance_scope)])


@router.get("/data-planes", tags=["Data Plane"], dependencies=[require(Scope.data_planes_read)])
async def list_data_planes(include_offline: bool = False) -> Envelope[list[DataPlaneInstanceOut]]:
    """Every data plane known to the instance; offline ones are kept as history and shown only with include_offline."""
    now = datetime.now(tz=UTC)
    instances = await DataPlaneInstance.find(order_by=col(DataPlaneInstance.last_seen).desc())
    out = [DataPlaneInstanceOut(**i.model_dump(), status=status) for i in instances if (status := i.status(now)) == "online" or include_offline]
    return Envelope(data=out)


@router.get("/management-keys", tags=["Instance Management Keys"], dependencies=[require(Scope.management_keys_read)])
async def list_all_management_keys(org_id: str | None = None) -> Envelope[list[ManagementKeyOut]]:
    """Instance-wide oversight: every management key, optionally filtered to one org."""
    conditions = (ManagementKey.org_id == org_id,) if org_id else ()
    return Envelope(data=[ManagementKeyOut.model_validate(r) for r in await ManagementKey.find(*conditions, order_by=col(ManagementKey.id))])


@router.post("/management-keys", tags=["Instance Management Keys"], dependencies=[require(Scope.management_keys_write)])
async def mint_instance_management_key(body: ManagementKeyIn, claims: MgmtDep) -> Envelope[ManagementKeyMintedOut]:
    """Mint an instance-scoped key; the holding user must be an instance admin."""
    user_id = body.user_id or claims.user_id
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404)
    if not user.instance_admin:
        raise HTTPException(status_code=403)
    scopes = [s.value for s in body.scopes] if body.scopes is not None else None
    key_id, token = await mint_management_key(None, user_id, label=body.label, scopes=scopes)
    return Envelope(data=ManagementKeyMintedOut(id=key_id, org_id=None, user_id=user_id, scopes=scopes, label=body.label, token=token))


@router.delete("/management-keys/{key_id}", tags=["Instance Management Keys"], dependencies=[require(Scope.management_keys_write)])
async def revoke_any_management_key(key_id: UUID) -> Envelope[ManagementKeyRevokedOut]:
    key = await ManagementKey.find_by_id(key_id)
    if key is None:
        raise HTTPException(status_code=404)
    key.revoked = True
    await key.save()
    return Envelope(data=ManagementKeyRevokedOut(id=key_id, status="revoked"))
