from __future__ import annotations

from uuid import UUID

from sqlmodel import Field, UniqueConstraint, select

from control_plane.db import current_session
from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.user import User
from control_plane.passwords import hash_password

PASSWORD_PROVIDER = "password"  # noqa: S105 provider discriminator, not a secret


class IdentityConflictError(RuntimeError):
    pass


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
        return await cls.first(cls.provider == PASSWORD_PROVIDER, cls.subject == User.normalize_email(email))

    @classmethod
    async def password_for_update(cls, email: str) -> AuthIdentity | None:
        query = select(cls).where(cls.provider == PASSWORD_PROVIDER, cls.subject == User.normalize_email(email)).with_for_update()
        return (await current_session().execute(query)).scalar_one_or_none()

    @classmethod
    async def set_password(cls, user: User, password: str) -> AuthIdentity:
        identity = await cls.password_for(user.email)
        if identity is not None and identity.user_id != user.id:
            raise IdentityConflictError
        identity = identity or cls(user_id=user.id, provider=PASSWORD_PROVIDER, subject=User.normalize_email(user.email))
        identity.secret_hash = hash_password(password)
        return await identity.save()
