from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON
from sqlmodel import Field, SQLModel


class Org(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    created_at: datetime


class ApiKey(SQLModel, table=True):
    id: str = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    allowed_models: list[str] = Field(default_factory=list, sa_type=JSON)
    disabled: bool = False
    created_at: datetime


class Provider(SQLModel, table=True):
    id: str = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    kind: str
    base_url: str
    credential_ref: str


class Model(SQLModel, table=True):
    id: str = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    provider_id: str = Field(foreign_key="provider.id")
    upstream_model: str
    input_price_per_mtok: float
    output_price_per_mtok: float
    context_window: int
    max_output_tokens: int | None = None
    capabilities: list[str] = Field(default_factory=list, sa_type=JSON)


class Bundle(SQLModel, table=True):
    id: UUID = Field(primary_key=True)
    org_id: str = Field(foreign_key="org.id")
    version: int
    issued_at: datetime
    expires_at: datetime
    payload: str
    signature: str
    signing_key_id: str


class UsageEvent(SQLModel, table=True):
    event_id: UUID = Field(primary_key=True)
    request_id: str
    occurred_at: datetime
    org_id: str
    key_id: str
    model_id: str
    provider_id: str
    bundle_id: UUID
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cost_input_usd: float = 0.0
    cost_output_usd: float = 0.0
    latency_ms: int
    status: str
    stream: bool


class DataPlaneInstance(SQLModel, table=True):
    instance_id: str = Field(primary_key=True)
    version: str
    bundle_id: UUID | None = None
    last_seen: datetime
