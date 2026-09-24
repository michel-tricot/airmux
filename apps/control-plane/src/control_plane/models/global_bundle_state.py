from __future__ import annotations

from sqlalchemy import BigInteger
from sqlmodel import Field

from control_plane.models.common.base import Record


class GlobalBundleState(Record, table=True):
    id: int = Field(default=1, primary_key=True)
    desired_generation: int = Field(default=0, sa_type=BigInteger)
