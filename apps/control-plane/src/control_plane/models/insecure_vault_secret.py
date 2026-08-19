from __future__ import annotations

from typing import ClassVar

from sqlmodel import Field

from control_plane.models.common.base import Record


class InsecureVaultSecret(Record, table=True):
    address: str = Field(primary_key=True, max_length=64)
    value: str

    api_hidden: ClassVar[frozenset[str]] = frozenset({"address", "value"})
