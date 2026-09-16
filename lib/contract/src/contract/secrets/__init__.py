from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID  # noqa: TC003 SecretRef crosses the wire inside the bundle, so pydantic resolves this at runtime


class SecretPurpose(StrEnum):
    provider = "provider"


@dataclass(frozen=True)
class SecretRef:
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
