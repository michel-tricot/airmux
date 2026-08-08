from __future__ import annotations

from pathlib import Path
from uuid import UUID  # noqa: TC003 fastapi resolves path param annotations at runtime

from anyio.to_thread import run_sync
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import col

from control_plane.authz import Scope
from control_plane.deps import SessionDep, instance_scope, public, require
from control_plane.keys import MANAGEMENT_KEY_PREFIX
from control_plane.models import DataPlaneInstance, ManagementKey, User
from control_plane.models.common.wire import Envelope
from control_plane.models.management_key import ManagementKeyOut, ManagementKeyRevokedOut

router = APIRouter(prefix="/instance", dependencies=[Depends(instance_scope)])

claim_router = APIRouter(prefix="/instance")

DATA_PLANE_KEY_FILE = "dataplane.key"
# Where the data plane looks for its token: the docker shared volume first, then the local cache dir.
DATA_PLANE_KEY_DIRS = (Path("/state"), Path(".airllm"))


class ClaimOut(BaseModel):
    claimed: bool


@claim_router.get("/claim", tags=["Instance"], dependencies=[public()])
async def claim(_session: SessionDep) -> Envelope[ClaimOut]:
    """Whether any human holds an account yet: public so a fresh deployment can route its first visitor to signup.

    Service accounts do not claim an instance; it leaks nothing beyond set-up-or-not, like healthz.
    """
    return Envelope(data=ClaimOut(claimed=await User.first(col(User.service_account).is_(False)) is not None))


class OssQuickstartIn(BaseModel):
    token: str


class OssQuickstartOut(BaseModel):
    path: str


@claim_router.post("/oss-quickstart", tags=["Instance"], dependencies=[public()])
async def oss_quickstart(body: OssQuickstartIn, _session: SessionDep) -> Envelope[OssQuickstartOut]:
    """Drop the data plane's management token onto the shared volume so the first data plane can boot.

    A single-use bootstrap trapdoor: public, but it only fires while no data plane has ever
    registered, and it closes the moment one heartbeats. The caller already holds the token it
    writes, so nothing is minted or leaked here; the endpoint only bridges a token the operator
    has into the file the co-mounted data plane container waits for.
    """
    if await DataPlaneInstance.first() is not None:
        raise HTTPException(status_code=409, detail="a data plane has already registered; quickstart is closed")
    if not body.token.startswith(MANAGEMENT_KEY_PREFIX):
        raise HTTPException(status_code=422, detail=f"token must be a management key ({MANAGEMENT_KEY_PREFIX}...)")
    return Envelope(data=OssQuickstartOut(path=await run_sync(_write_data_plane_key, body.token)))


def _write_data_plane_key(token: str) -> str:
    directory = next((d for d in DATA_PLANE_KEY_DIRS if d.is_dir()), None)
    if directory is None:
        joined = " or ".join(str(d) for d in DATA_PLANE_KEY_DIRS)
        raise HTTPException(status_code=503, detail=f"no data plane state directory to write to ({joined})")
    destination = directory / DATA_PLANE_KEY_FILE
    destination.write_text(token, encoding="utf-8")
    return str(destination)


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
