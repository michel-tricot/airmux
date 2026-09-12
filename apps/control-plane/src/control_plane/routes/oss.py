from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from control_plane.deps import public
from control_plane.models import User
from control_plane.models.common.wire import Envelope

router = APIRouter(prefix="/instance/oss", tags=["OSS"])


class ClaimOut(BaseModel):
    claimed: bool
    public_signup: bool


@router.get("/claim", dependencies=[public("api")])
async def claim(request: Request) -> Envelope[ClaimOut]:
    """Return whether a human account has claimed this deployment."""
    return Envelope(data=ClaimOut(claimed=await User.instance_claimed(), public_signup=request.app.state.settings.public_signup))
