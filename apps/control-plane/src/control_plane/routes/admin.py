from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/admin")


@router.post("/orgs")
async def create_org() -> dict[str, str]:
    raise NotImplementedError


@router.post("/keys")
async def create_key() -> dict[str, str]:
    raise NotImplementedError


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: str) -> dict[str, str]:
    raise NotImplementedError


@router.post("/providers")
async def create_provider() -> dict[str, str]:
    raise NotImplementedError


@router.post("/models")
async def create_model() -> dict[str, str]:
    raise NotImplementedError


@router.post("/bundles/compile")
async def compile_bundle() -> dict[str, str]:
    raise NotImplementedError
