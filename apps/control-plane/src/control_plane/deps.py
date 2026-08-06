from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from control_plane.db import current_actor, transaction
from control_plane.tokens import ManagementClaims, verify_management_token

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

_bearer = HTTPBearer(auto_error=False)

BearerDep = Annotated["HTTPAuthorizationCredentials | None", Depends(_bearer)]


async def management_claims(credentials: BearerDep, _session: SessionDep) -> ManagementClaims:
    claims = await verify_management_token(credentials.credentials) if credentials else None
    if claims is None:
        raise HTTPException(status_code=401)
    current_actor.set(claims.user_id)
    return claims


MgmtDep = Annotated[ManagementClaims, Depends(management_claims)]


async def instance_scope(claims: MgmtDep) -> ManagementClaims:
    if claims.org_id is not None:
        raise HTTPException(status_code=403)
    return claims


async def org_scope(claims: MgmtDep) -> str:
    if claims.org_id is None:
        raise HTTPException(status_code=403)
    return claims.org_id


InstanceDep = Annotated[ManagementClaims, Depends(instance_scope)]
OrgDep = Annotated[str, Depends(org_scope)]


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with transaction(request.app.state.session_factory) as session:
        yield session


SessionDep = Annotated["AsyncSession", Depends(get_session, scope="function")]
