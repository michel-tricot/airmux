from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/v1")


@router.get("/bundle/latest")
async def bundle_latest() -> dict[str, str]:
    raise NotImplementedError


@router.post("/events")
async def ingest_events() -> dict[str, int]:
    raise NotImplementedError


@router.post("/heartbeat")
async def heartbeat() -> dict[str, str]:
    raise NotImplementedError
