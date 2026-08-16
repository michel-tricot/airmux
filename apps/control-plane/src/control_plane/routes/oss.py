from __future__ import annotations

from pathlib import Path

from anyio.to_thread import run_sync
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from contract.secrets.file import write_private_text
from control_plane.deps import public
from control_plane.keys import INSTANCE_KEY_PREFIX, MANAGEMENT_KEY_PREFIX
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
    """Whether any human holds an account yet: public so a fresh deployment can route its first visitor to signup.

    Service accounts do not claim an instance; it leaks nothing beyond set-up-or-not, like healthz.
    """
    return Envelope(data=ClaimOut(claimed=await User.instance_claimed()))


class QuickstartIn(RequestModel):
    token: str = Field(min_length=1, max_length=512)


class QuickstartOut(BaseModel):
    path: str


@router.post("/quickstart", dependencies=[public()])
async def quickstart(body: QuickstartIn) -> Envelope[QuickstartOut]:
    """Drop the data plane's sync credential onto the shared volume so the first data plane can boot.

    A single-use bootstrap trapdoor: public, but it only fires while no data plane has ever
    registered, and it closes the moment one heartbeats. The caller already holds the token it
    writes, so nothing is minted or leaked here; the endpoint only bridges a token the operator
    has into the file the co-mounted data plane container waits for.

    Either control-plane key type can drive a data plane: a management key pins it to one org's
    bundles, an instance key leaves the org to its config. The prefix check only catches a token
    that could never work at all, an inference key or a paste accident.
    """
    if await DataPlaneInstance.first() is not None:
        raise HTTPException(status_code=409, detail="a data plane has already registered; quickstart is closed")
    if not body.token.startswith((MANAGEMENT_KEY_PREFIX, INSTANCE_KEY_PREFIX)):
        accepted = f"{MANAGEMENT_KEY_PREFIX}... or {INSTANCE_KEY_PREFIX}..."
        raise HTTPException(status_code=422, detail=f"token must be a management or instance key ({accepted})")
    return Envelope(data=QuickstartOut(path=await run_sync(_write_data_plane_key, body.token)))


def _write_data_plane_key(token: str) -> str:
    destination = DATA_PLANE_KEY_DIR / DATA_PLANE_KEY_FILE
    write_private_text(destination, token)
    return str(destination.resolve())
