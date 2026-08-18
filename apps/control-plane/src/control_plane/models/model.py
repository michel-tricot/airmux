from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON
from sqlmodel import Field

from control_plane.models.audit import audited
from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordOut
from control_plane.models.runtime_configuration import runtime_configured


@audited
@runtime_configured(
    scope="global",
    columns=(
        "name",
        "provider_id",
        "upstream_model",
        "egress_kind",
        "input_price_per_mtok",
        "output_price_per_mtok",
        "cache_read_price_per_mtok",
        "cache_write_price_per_mtok",
        "context_window",
        "max_output_tokens",
        "capabilities",
    ),
)
class Model(Record, Identified, Tombstonable, table=True):
    name: str = Field(unique=True)
    provider_id: UUID = Field(foreign_key="provider.id")
    upstream_model: str
    egress_kind: str | None = None
    input_price_per_mtok: float
    output_price_per_mtok: float
    cache_read_price_per_mtok: float
    cache_write_price_per_mtok: float
    context_window: int
    max_output_tokens: int | None = None
    capabilities: list[str] = Field(default_factory=list, sa_type=JSON)


class ModelOut(RecordOut[Model]):
    id: UUID
    name: str
    provider_id: UUID
    upstream_model: str
    egress_kind: str | None
    input_price_per_mtok: float
    output_price_per_mtok: float
    cache_read_price_per_mtok: float
    cache_write_price_per_mtok: float
    context_window: int
    max_output_tokens: int | None
    capabilities: list[str]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
