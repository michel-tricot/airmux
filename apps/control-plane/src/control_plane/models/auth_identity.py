from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import Field, UniqueConstraint

from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.passwords import hash_password

if TYPE_CHECKING:
    from control_plane.models.user import User

PASSWORD_PROVIDER = "password"  # noqa: S105 provider discriminator, not a secret


class AuthIdentity(Record, Identified, Tombstonable, table=True):
    """A way a user proves who they are: provider is "password" or "oidc:<connection_id>", subject
    is the provider-stable handle (lowercased email for password, the IdP sub claim for oidc).

    Internal table with no api models; it never crosses the wire. Not audited: snapshots would
    copy secret hashes into AuditLog rows.
    """

    __table_args__ = (UniqueConstraint("provider", "subject"),)

    user_id: UUID = Field(foreign_key="user.id")
    provider: str
    subject: str
    secret_hash: str | None = None

    @classmethod
    async def password_for(cls, email: str) -> AuthIdentity | None:
        return await cls.first(cls.provider == PASSWORD_PROVIDER, cls.subject == email.lower())

    @classmethod
    async def set_password(cls, user: User, password: str) -> AuthIdentity:
        """Upsert the user's password identity with a fresh hash; callers own the policy of when that is allowed."""
        identity = await cls.password_for(user.email) or cls(user_id=user.id, provider=PASSWORD_PROVIDER, subject=user.email.lower())
        identity.secret_hash = hash_password(password)
        return await identity.save()
