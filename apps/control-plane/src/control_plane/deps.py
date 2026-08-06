from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from control_plane.db import current_actor, transaction
from control_plane.models import MgmtToken, OrgMembership, User
from control_plane.tokens import ManagementClaims, verify_management_token

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

_bearer = HTTPBearer(auto_error=False)

BearerDep = Annotated["HTTPAuthorizationCredentials | None", Depends(_bearer)]


async def claims_are_backed(claims: ManagementClaims) -> bool:
    """The database-backed half of management auth: revocation and the user backing the claimed scope.

    Shared between request auth (below) and setup's stored-token liveness check, so the CLI can
    never keep a token the server would 401.
    """
    row = await MgmtToken.get(claims.token_id)
    if row is not None and row.revoked:
        return False
    if claims.user_id is None:
        return True
    user = await User.get(claims.user_id)
    if user is None:
        return False
    if user.instance_admin:
        return True
    return claims.org_id is not None and await OrgMembership.get((claims.user_id, claims.org_id)) is not None


async def management_claims(request: Request, credentials: BearerDep, _session: SessionDep) -> ManagementClaims:
    claims = verify_management_token(credentials.credentials, request.app.state.token_public_key) if credentials else None
    if claims is None or not await claims_are_backed(claims):
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
