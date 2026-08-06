from __future__ import annotations

from sqlmodel import Field, UniqueConstraint

from control_plane.models.base import Record
from control_plane.models.mixins import Tombstonable


class AuthIdentity(Record, Tombstonable, table=True):
    """A way a user proves who they are: provider is "password" or "oidc:<connection_id>", subject
    is the provider-stable handle (lowercased email for password, the IdP sub claim for oidc).

    Internal table with no api models; it never crosses the wire. Not audited: snapshots would
    copy secret hashes into AuditLog rows.
    """

    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id")
    provider: str
    subject: str
    secret_hash: str | None = None
