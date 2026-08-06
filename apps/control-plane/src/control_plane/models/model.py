from __future__ import annotations

from datetime import datetime  # noqa: TC003 pydantic resolves field annotations at runtime

from sqlalchemy import JSON
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.base import Record
from control_plane.models.mixins import Tombstonable
from control_plane.schemas import ApiOut


@audited
class Model(Record, Tombstonable, table=True):
    id: str = Field(primary_key=True)
    provider_id: str = Field(foreign_key="provider.id")
    upstream_model: str
    input_price_per_mtok: float
    output_price_per_mtok: float
    context_window: int
    max_output_tokens: int | None = None
    capabilities: list[str] = Field(default_factory=list, sa_type=JSON)


class ModelOut(ApiOut):
    id: str
    provider_id: str
    upstream_model: str
    input_price_per_mtok: float
    output_price_per_mtok: float
    context_window: int
    max_output_tokens: int | None
    capabilities: list[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
