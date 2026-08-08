from __future__ import annotations

from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col

from control_plane.authz import Scope
from control_plane.deps import instance_scope, require
from control_plane.models import ManagementKey
from control_plane.models.common.wire import Envelope
from control_plane.models.management_key import ManagementKeyOut, ManagementKeyRevokedOut

router = APIRouter(prefix="/instance", dependencies=[Depends(instance_scope)])


@router.get("/tokens", tags=["Management Tokens"], dependencies=[require(Scope.tokens_read)])
async def list_tokens(org_id: str | None = None) -> Envelope[list[ManagementKeyOut]]:
    conditions = (ManagementKey.org_id == org_id,) if org_id else ()
    return Envelope(data=[ManagementKeyOut.model_validate(r) for r in await ManagementKey.find(*conditions, order_by=col(ManagementKey.id))])


@router.delete("/tokens/{token_id}", tags=["Management Tokens"], dependencies=[require(Scope.tokens_write)])
async def revoke_token(token_id: UUID) -> Envelope[ManagementKeyRevokedOut]:
    key = await ManagementKey.find_by_id(token_id)
    if key is None:
        raise HTTPException(status_code=404)
    key.revoked = True
    await key.save()
    return Envelope(data=ManagementKeyRevokedOut(id=token_id, status="revoked"))
