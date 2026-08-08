from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from contract import token_hash
from control_plane.models import AuthSession

if TYPE_CHECKING:
    from uuid import UUID

SESSION_TOKEN_PREFIX = "sk-sess-"  # noqa: S105 token prefix, not a secret
SESSION_COOKIE = "airllm_session"
SESSION_IDLE_TTL = timedelta(hours=12)
SESSION_ABSOLUTE_TTL = timedelta(days=14)


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def mint_session(user_id: UUID) -> tuple[AuthSession, str]:
    """Mint a session row and its cookie token; the plaintext exists only in the return value.

    Every login mints a fresh row, so a session id can never be fixated. Runs inside the
    caller's transaction.
    """
    token = SESSION_TOKEN_PREFIX + secrets.token_urlsafe(32)
    now = datetime.now(tz=UTC)
    auth_session = await AuthSession(
        user_id=user_id,
        token_hash=token_hash(token),
        expires_at=now + SESSION_IDLE_TTL,
        absolute_expires_at=now + SESSION_ABSOLUTE_TTL,
    ).save()
    return auth_session, token


async def verify_session(token: str) -> AuthSession | None:
    """Resolve a presented cookie token; returns None on any failure.

    Expired rows are inert, not deleted here: the 401 that follows rolls the request
    transaction back, so a delete could never stick. The idle expiry slides, but only once
    past half-life, so an active session costs about one write per six hours, capped at the
    absolute expiry set at login.
    """
    if not token.startswith(SESSION_TOKEN_PREFIX):
        return None
    auth_session = await AuthSession.first(AuthSession.token_hash == token_hash(token))
    if auth_session is None:
        return None
    now = datetime.now(tz=UTC)
    if aware(auth_session.expires_at) <= now or aware(auth_session.absolute_expires_at) <= now:
        return None
    if aware(auth_session.expires_at) - now < SESSION_IDLE_TTL / 2:
        auth_session.expires_at = min(now + SESSION_IDLE_TTL, aware(auth_session.absolute_expires_at))
        await auth_session.save()
    return auth_session
