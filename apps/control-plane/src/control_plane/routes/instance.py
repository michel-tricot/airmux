from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col

from control_plane.authz import Scope
from control_plane.deps import MgmtDep, instance_scope, require
from control_plane.keys import mint_instance_key
from control_plane.models import AuditLog, DataPlaneInstance, InstanceKey, ManagementKey, User
from control_plane.models.audit import ActivityOut
from control_plane.models.common.wire import Envelope
from control_plane.models.data_plane_instance import DataPlaneInstanceOut
from control_plane.models.instance_key import InstanceKeyIn, InstanceKeyMintedOut, InstanceKeyOut, InstanceKeyRevokedOut
from control_plane.models.management_key import ManagementKeyOut, ManagementKeyRevokedOut

router = APIRouter(prefix="/instance", dependencies=[Depends(instance_scope)])


@router.get("/data-planes", tags=["Data Plane"], dependencies=[require(Scope.data_planes_read)])
async def list_data_planes(include_offline: bool = False) -> Envelope[list[DataPlaneInstanceOut]]:
    """Every data plane known to the instance; offline ones are kept as history and shown only with include_offline."""
    now = datetime.now(tz=UTC)
    instances = await DataPlaneInstance.find(order_by=col(DataPlaneInstance.last_seen).desc())
    out = [DataPlaneInstanceOut(**i.model_dump(), status=status) for i in instances if (status := i.status(now)) == "online" or include_offline]
    return Envelope(data=out)


@router.get("/instance-keys", tags=["Instance Keys"], dependencies=[require(Scope.instance_keys_read)])
async def list_instance_keys() -> Envelope[list[InstanceKeyOut]]:
    """Every instance key on the deployment; there is no org axis to filter on."""
    keys = await InstanceKey.find(order_by=col(InstanceKey.id))
    return Envelope(data=[InstanceKeyOut.model_validate(k) for k in keys])


@router.post("/instance-keys", tags=["Instance Keys"], dependencies=[require(Scope.instance_keys_write)])
async def create_instance_key(body: InstanceKeyIn, claims: MgmtDep) -> Envelope[InstanceKeyMintedOut]:
    """Mint an instance key for the acting admin, or for another instance admin when user_id names one."""
    user_id = body.user_id or claims.user_id
    user = await User.find_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.instance_admin:
        raise HTTPException(status_code=403, detail="instance keys are only minted for instance admins")
    scopes = [s.value for s in body.scopes] if body.scopes is not None else None
    key_id, token = await mint_instance_key(user_id, label=body.label, scopes=scopes)
    return Envelope(data=InstanceKeyMintedOut(id=key_id, user_id=user_id, scopes=scopes, label=body.label, token=token))


@router.delete("/instance-keys/{key_id}", tags=["Instance Keys"], dependencies=[require(Scope.instance_keys_write)])
async def revoke_instance_key(key_id: UUID) -> Envelope[InstanceKeyRevokedOut]:
    key = await InstanceKey.find_by_id(key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Instance key not found")
    key.revoked = True
    await key.save()
    return Envelope(data=InstanceKeyRevokedOut(id=key_id, status="revoked"))


@router.get("/management-keys", tags=["Instance Management Keys"], dependencies=[require(Scope.management_keys_read)])
async def list_all_management_keys(org_id: UUID | None = None) -> Envelope[list[ManagementKeyOut]]:
    """Instance-wide oversight: every org's management keys, optionally filtered to one org."""
    conditions = (ManagementKey.org_id == org_id,) if org_id else ()
    return Envelope(data=[ManagementKeyOut.model_validate(k) for k in await ManagementKey.find(*conditions, order_by=col(ManagementKey.id))])


@router.delete("/management-keys/{key_id}", tags=["Instance Management Keys"], dependencies=[require(Scope.management_keys_write)])
async def revoke_any_management_key(key_id: UUID) -> Envelope[ManagementKeyRevokedOut]:
    """Revoke any org's management key; the org-scoped route reaches only its own."""
    key = await ManagementKey.find_by_id(key_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Management key not found")
    key.revoked = True
    await key.save()
    return Envelope(data=ManagementKeyRevokedOut(id=key_id, status="revoked"))


@router.get("/activity", tags=["Activity"], dependencies=[require(Scope.activity_read)])
async def list_instance_activity(limit: int = 50) -> Envelope[list[ActivityOut]]:
    """What changed anywhere on the instance, newest first; the org-scoped view of the same trail is /org/activity."""
    return Envelope(data=[ActivityOut.model_validate(entry) for entry in await AuditLog.recent(limit)])
