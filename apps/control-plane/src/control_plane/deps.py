from __future__ import annotations

import hmac
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

_bearer = HTTPBearer(auto_error=False)

BearerDep = Annotated["HTTPAuthorizationCredentials | None", Depends(_bearer)]


def _matches(credentials: HTTPAuthorizationCredentials | None, expected: str) -> bool:
    return credentials is not None and hmac.compare_digest(credentials.credentials, expected)


async def require_admin(request: Request, credentials: BearerDep) -> None:
    if not _matches(credentials, request.app.state.settings.auth.admin_token):
        raise HTTPException(status_code=401)


async def require_dp(request: Request, credentials: BearerDep) -> None:
    if not _matches(credentials, request.app.state.settings.auth.dp_token):
        raise HTTPException(status_code=401)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated["AsyncSession", Depends(get_session)]
