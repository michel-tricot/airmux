from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select

from contract import BundleV1, SignedBundle
from control_plane.deps import SessionDep, require_dp
from control_plane.models import Bundle

router = APIRouter(prefix="/v1", dependencies=[Depends(require_dp)])


@router.get("/bundle/latest")
async def bundle_latest(session: SessionDep) -> SignedBundle:
    row = (await session.execute(select(Bundle).order_by(Bundle.issued_at.desc(), Bundle.version.desc()).limit(1))).scalars().first()
    if row is None:
        raise HTTPException(status_code=404)
    return SignedBundle(payload=BundleV1.model_validate_json(row.payload), signature=row.signature, signing_key_id=row.signing_key_id)


@router.post("/events")
async def ingest_events() -> dict[str, int]:
    raise NotImplementedError


@router.post("/heartbeat")
async def heartbeat() -> dict[str, str]:
    raise NotImplementedError
