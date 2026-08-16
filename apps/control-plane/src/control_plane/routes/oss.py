from __future__ import annotations

from pathlib import Path

from anyio.to_thread import run_sync
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from contract.secrets.file import write_private_text
from control_plane.authz import DATA_PLANE_PERMISSIONS, Boundary, OrgRole
from control_plane.deps import public
from control_plane.keys import ACCESS_KEY_PREFIX, verify_access_key
from control_plane.models import DataPlaneInstance, OrgMembership, User
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

    The accepted key authenticates a service account with the data-plane role and exactly the three
    runtime permissions. The prefix check catches an inference key or a paste accident early.
    """
    if await DataPlaneInstance.first() is not None:
        raise HTTPException(status_code=409, detail="a data plane has already registered; quickstart is closed")
    authority = await verify_access_key(body.token)
    user = await User.find_by_id(authority.principal_id) if authority is not None else None
    membership = await OrgMembership.get((authority.principal_id, authority.org_id)) if authority is not None and authority.org_id else None
    if (
        not body.token.startswith(ACCESS_KEY_PREFIX)
        or authority is None
        or authority.boundary is not Boundary.org
        or authority.permission_ceiling != DATA_PLANE_PERMISSIONS
        or user is None
        or not user.service_account
        or membership is None
        or membership.role != OrgRole.data_plane
    ):
        raise HTTPException(status_code=422, detail="token must be a live org-bound data-plane access key")
    return Envelope(data=QuickstartOut(path=await run_sync(_write_data_plane_key, body.token)))


def _write_data_plane_key(token: str) -> str:
    destination = DATA_PLANE_KEY_DIR / DATA_PLANE_KEY_FILE
    write_private_text(destination, token)
    return str(destination.resolve())
