from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON
from sqlmodel import Field

from contract import Capability, Modality, ParameterSupport
from contract.taxonomy import ModelSpec
from control_plane.models.audit import audited
from control_plane.models.common import Identified, Tombstonable
from control_plane.models.common.base import Record
from control_plane.models.common.wire import RecordOut, RequestModel
from control_plane.models.runtime_configuration import bundle_input


@audited
@bundle_input(
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
        "input_modalities",
        "output_modalities",
        "capabilities",
        "parameter_support",
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
    input_modalities: list[Modality] = Field(sa_type=JSON, min_length=1, nullable=False)
    output_modalities: list[Modality] = Field(sa_type=JSON, min_length=1, nullable=False)
    capabilities: list[Capability] = Field(default_factory=list, sa_type=JSON)
    parameter_support: dict[str, ParameterSupport] = Field(default_factory=dict, sa_type=JSON)


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
    input_modalities: list[Modality]
    output_modalities: list[Modality]
    capabilities: list[Capability]
    parameter_support: dict[str, ParameterSupport]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class ModelIn(ModelSpec, RequestModel):
    pass
