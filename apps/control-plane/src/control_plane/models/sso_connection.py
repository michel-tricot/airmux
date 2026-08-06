from __future__ import annotations

from datetime import datetime  # noqa: TC003 pydantic resolves field annotations at runtime
from typing import ClassVar

from pydantic import BaseModel
from sqlalchemy import JSON
from sqlmodel import Field

from control_plane.models.base import Record
from control_plane.models.mixins import OrgOwned, Tombstonable
from control_plane.schemas import ApiOut


class SsoConnection(Record, OrgOwned, Tombstonable, table=True):
    """An org's OIDC issuer: WorkOS, Keycloak, or any broker presenting as OIDC.

    The three endpoint columns are cached from the issuer's discovery document at create time, so
    /auth/sso/start needs no outbound call. email_domains drives home-realm discovery; jit allows
    first-login user provisioning into the org. Not audited: snapshots would copy client_secret
    into AuditLog rows.
    """

    id: str = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    issuer: str
    client_id: str
    client_secret: str
    email_domains: list[str] = Field(default_factory=list, sa_type=JSON)
    jit: bool = False
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"client_secret"})
    api_readonly: ClassVar[frozenset[str]] = frozenset({"id", "authorization_endpoint", "token_endpoint", "jwks_uri"})


class SsoConnectionOut(ApiOut):
    id: str
    org_id: str
    issuer: str
    client_id: str
    email_domains: list[str]
    jit: bool
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class SsoConnectionIn(BaseModel):
    issuer: str
    client_id: str
    client_secret: str
    email_domains: list[str]
    jit: bool = False
