from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field

from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.column_types import UTCDateTime
from control_plane.models.playground_session import PlaygroundSession


class AuthSession(Record, Identified, Tombstonable, table=True):
    """A browser session: the cookie holds the opaque token, this row holds its hash and expiry.

    expires_at slides on activity; absolute_expires_at is the hard cap set at login. Internal
    table with no api models. Not audited: the sliding refresh writes before the actor is known,
    and sessions are high-churn noise.
    """

    user_id: UUID = Field(foreign_key="user.id")
    token_hash: str = Field(unique=True)
    expires_at: datetime = Field(sa_type=UTCDateTime)
    absolute_expires_at: datetime = Field(sa_type=UTCDateTime)

    async def delete(self) -> None:
        await PlaygroundSession.revoke_credential(self.id)
        await super().delete()
