from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contract import EnvStoreConfig, SecretsConfig, load_config_section
from data_plane.bundle.config import BundleConfig


class ControlPlaneLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str | None = None  # None means file-only mode, no polling
    token: str | None = None
    heartbeat_interval_s: float = 30.0


class SqliteOutboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["sqlite"] = "sqlite"
    flush_interval_s: float = 5.0
    cache_dir: Path = Path(".airllm")  # where the sqlite outbox lives; workers sharing it share one queue


class DevNullOutboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["devnull"] = "devnull"


OutboxConfig = Annotated[SqliteOutboxConfig | DevNullOutboxConfig, Field(discriminator="kind")]


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_plane: ControlPlaneLink = Field(default_factory=ControlPlaneLink)
    bundle: BundleConfig
    secrets: SecretsConfig = Field(default_factory=EnvStoreConfig)  # where provider keys live; must name the store the control plane writes
    events: OutboxConfig = Field(default_factory=DevNullOutboxConfig)
    dev: bool = False  # set by the --dev flag on the entry point, gate dev-only behavior on this

    @model_validator(mode="after")
    def require_control_plane_for_sqlite_outbox(self) -> Config:
        if isinstance(self.events, SqliteOutboxConfig) and not self.control_plane.url:
            msg = "sqlite event outbox requires data_plane.control_plane.url"
            raise ValueError(msg)
        return self


def load_config() -> Config:
    section = load_config_section("data_plane")
    return Config.model_validate({**section, "dev": os.environ.get("GW_DEV") == "1"})
