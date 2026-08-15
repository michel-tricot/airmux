from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contract import EnvStoreConfig, SecretsConfig, load_config_section
from data_plane.bundle.config import BundleConfig


class ControlPlaneLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str = Field(min_length=1)
    token: str = Field(min_length=1)
    heartbeat_interval_s: float = Field(default=30.0, gt=0)


class SqliteOutboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["sqlite"] = "sqlite"
    flush_interval_s: float = Field(default=5.0, gt=0)
    cache_dir: Path = Path(".airllm")  # where the sqlite outbox lives; workers sharing it share one queue


class DevNullOutboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["devnull"] = "devnull"


OutboxConfig = Annotated[SqliteOutboxConfig | DevNullOutboxConfig, Field(discriminator="kind")]


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_plane: ControlPlaneLink | None = None
    bundle: BundleConfig
    secrets: SecretsConfig = Field(default_factory=EnvStoreConfig)  # where provider keys live; must name the store the control plane writes
    events: OutboxConfig = Field(default_factory=DevNullOutboxConfig)
    dev: bool = False  # set by the --dev flag on the entry point, gate dev-only behavior on this

    @model_validator(mode="after")
    def require_control_plane_for_connected_features(self) -> Config:
        if self.control_plane is not None:
            return self
        if self.bundle.kind == "remote":
            msg = "remote bundle requires data_plane.control_plane"
            raise ValueError(msg)
        if self.events.kind == "sqlite":
            msg = "sqlite event outbox requires data_plane.control_plane"
            raise ValueError(msg)
        return self


def load_config() -> Config:
    section = load_config_section("data_plane")
    return Config.model_validate({**section, "dev": os.environ.get("GW_DEV") == "1"})
