from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from control_plane.models.base import Record
from control_plane.models.mixins import Tombstonable


class AuthSession(Record, Tombstonable, table=True):
    """A browser session: the cookie holds the opaque token, this row holds its hash and expiry.

    expires_at slides on activity; absolute_expires_at is the hard cap set at login. Internal
    table with no api models. Not audited: the sliding refresh writes before the actor is known,
    and sessions are high-churn noise.
    """

    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id")
    token_hash: str = Field(unique=True)
    expires_at: datetime
    absolute_expires_at: datetime
