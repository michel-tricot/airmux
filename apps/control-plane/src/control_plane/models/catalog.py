from __future__ import annotations

from sqlalchemy import JSON
from sqlmodel import Field

from control_plane.models.base import OrgOwned


class Provider(OrgOwned, table=True):
    id: str = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    kind: str
    base_url: str
    credential_ref: str
    cache_read_multiplier: float = 1.0
    cache_write_multiplier: float = 1.0


class Model(OrgOwned, table=True):
    id: str = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    provider_id: str = Field(foreign_key="provider.id")
    upstream_model: str
    input_price_per_mtok: float
    output_price_per_mtok: float
    context_window: int
    max_output_tokens: int | None = None
    capabilities: list[str] = Field(default_factory=list, sa_type=JSON)
