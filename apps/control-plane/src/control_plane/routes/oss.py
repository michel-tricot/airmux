from __future__ import annotations

from pathlib import Path

from anyio.to_thread import run_sync
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from contract.secrets.file import write_private_text
from control_plane.authority import is_data_plane_credential
from control_plane.deps import public
from control_plane.keys import verify_access_key
from control_plane.models import DataPlaneInstance, User
from control_plane.models.common.wire import Envelope, RequestModel

router = APIRouter(prefix="/instance/oss", tags=["OSS"])

DATA_PLANE_KEY_FILE = "dataplane.key"
# Where the data plane looks for its token, relative to the working directory: the checkout's cache dir,
# and the same path inside the container, whose working directory is the shared /state volume.
DATA_PLANE_KEY_DIR = Path(".airllm")


class ClaimOut(BaseModel):
    claimed: bool


@router.get("/claim", dependencies=[public()])
async def claim() -> Envelope[ClaimOut]:
    """Return whether a human account has claimed this deployment."""
    return Envelope(data=ClaimOut(claimed=await User.instance_claimed()))


class QuickstartIn(RequestModel):
    token: str = Field(description="Existing limited access key for the first data plane", min_length=1, max_length=512)


class QuickstartOut(BaseModel):
    path: str


@router.post("/quickstart", dependencies=[public()])
async def quickstart(body: QuickstartIn) -> Envelope[QuickstartOut]:
    """Install an existing access key where the first co-located data plane can read it.

    This endpoint is available only until a data plane first registers. The key must authenticate a
    service account and carry exactly the bundle, event-ingestion, and heartbeat permissions.
    """
    if await DataPlaneInstance.first() is not None:
        raise HTTPException(status_code=409, detail="a data plane has already registered; quickstart is closed")
    actor = await verify_access_key(body.token)
    user = await User.find_by_id(actor.principal_id) if actor is not None else None
    if actor is None or user is None or not await is_data_plane_credential(actor, user):
        raise HTTPException(status_code=422, detail="token must be a live data-plane access key")
    return Envelope(data=QuickstartOut(path=await run_sync(_write_data_plane_key, body.token)))


def _write_data_plane_key(token: str) -> str:
    destination = DATA_PLANE_KEY_DIR / DATA_PLANE_KEY_FILE
    write_private_text(destination, token)
    return str(destination.resolve())
