from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID  # noqa: TC003 SecretRef crosses the wire inside the bundle, so pydantic resolves this at runtime


class SecretPurpose(StrEnum):
    """The kind of credential addressed by a secret reference."""

    provider = "provider"


@dataclass(frozen=True)
class SecretRef:
    """A stable reference to a secret value and the scope that owns it."""

    purpose: SecretPurpose
    service: str
    name: str
    secret_id: UUID
    org_id: UUID | None = None
    workspace_id: UUID | None = None


__all__ = [
    "SecretPurpose",
    "SecretRef",
]
