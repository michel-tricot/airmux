from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import ClassVar, Self
from uuid import UUID

from sqlalchemy import ForeignKeyConstraint
from sqlmodel import Field, col, select

from contract import token_hash
from control_plane.db import current_session
from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime

POLL_SECRET_PREFIX = "sk-cli-"  # noqa: S105 token prefix, not a secret
USER_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
AUTH_REQUEST_TTL = timedelta(minutes=10)


def _normalize_user_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").upper()


class CliAuthRequest(Record, Identified, Tombstonable, table=True):
    """A pending device authorization: the CLI holds the poll secret, the human confirms the user code.

    Only hashes of both are stored; open() is the only place the plaintexts exist. The management key
    is minted at poll time, after approval, so its plaintext never rests in the pending request;
    the poll that delivers it also deletes the request, making delivery one-time. Internal table
    with no api models. Not audited: pre-identity churn; the minted key carries the audit trail.
    """

    __table_args__: ClassVar = (
        ForeignKeyConstraint(["approved_user_id"], ["user.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["approved_org_id"], ["org.id"], ondelete="CASCADE"),
    )

    user_code_hash: str = Field(unique=True)
    poll_secret_hash: str = Field(unique=True)
    client_name: str
    requester: str
    expires_at: datetime = Field(sa_type=UTCDateTime)
    approved_user_id: UUID | None = None
    approved_org_id: UUID | None = None

    @classmethod
    async def open(cls, client_name: str, requester: str) -> tuple[Self, str, str]:
        """Open a pending authorization; returns (request, user_code, poll_secret). Runs inside the caller's transaction."""
        now = datetime.now(tz=UTC)
        for expired in await cls.find(col(cls.expires_at) <= now):
            await expired.delete()
        chars = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(8))
        user_code = f"{chars[:4]}-{chars[4:]}"
        poll_secret = POLL_SECRET_PREFIX + secrets.token_urlsafe(32)
        auth_request = await cls(
            user_code_hash=token_hash(_normalize_user_code(user_code)),
            poll_secret_hash=token_hash(poll_secret),
            client_name=client_name,
            requester=requester,
            expires_at=now + AUTH_REQUEST_TTL,
        ).save()
        return auth_request, user_code, poll_secret

    @classmethod
    async def by_user_code(cls, code: str) -> Self | None:
        return await cls.first(cls.user_code_hash == token_hash(_normalize_user_code(code)))

    @classmethod
    async def for_approval(cls, code: str) -> Self | None:
        query = select(cls).where(cls.user_code_hash == token_hash(_normalize_user_code(code))).with_for_update()
        return (await current_session().execute(query)).scalar_one_or_none()

    @classmethod
    async def for_delivery(cls, secret: str) -> Self | None:
        if not secret.startswith(POLL_SECRET_PREFIX):
            return None
        query = select(cls).where(cls.poll_secret_hash == token_hash(secret)).with_for_update()
        return (await current_session().execute(query)).scalar_one_or_none()

    @property
    def expired(self) -> bool:
        return self.expires_at <= datetime.now(tz=UTC)
