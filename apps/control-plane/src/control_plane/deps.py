from __future__ import annotations

import hmac
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException, Request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession


def _bearer_matches(authorization: str, expected: str) -> bool:
    return authorization.startswith("Bearer ") and hmac.compare_digest(authorization.removeprefix("Bearer "), expected)


async def require_admin(request: Request, authorization: Annotated[str, Header()] = "") -> None:
    if not _bearer_matches(authorization, request.app.state.settings.auth.admin_token):
        raise HTTPException(status_code=401)


async def require_dp(request: Request, authorization: Annotated[str, Header()] = "") -> None:
    if not _bearer_matches(authorization, request.app.state.settings.auth.dp_token):
        raise HTTPException(status_code=401)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated["AsyncSession", Depends(get_session)]
