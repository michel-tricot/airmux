from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from control_plane.models.base import Record
from control_plane.models.mixins import Tombstonable


class LoginAttempt(Record, Tombstonable, table=True):
    """One in-flight OIDC authorization: created at /auth/sso/start, consumed once at the callback.

    state is the primary key and the browser round-trip correlation handle; nonce binds the
    id_token, code_verifier is the PKCE secret. Internal table with no api models, not audited.
    """

    state: str = Field(primary_key=True)
    connection_id: str = Field(foreign_key="sso_connection.id")
    nonce: str
    code_verifier: str
    expires_at: datetime
