from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from airmux_runtime.config import ConfigContext, ConfigPath, load_config_section
from airmux_runtime.secrets import EnvStoreConfig, SecretsConfig
from data_plane.bundle.config import BundleConfig
from data_plane.control_plane_link import ControlPlaneLink


class SqliteOutboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["sqlite"] = "sqlite"
    control_plane: ControlPlaneLink
    flush_interval_s: float = Field(default=5.0, gt=0)
    cache_dir: ConfigPath = Path(".airmux")  # where the sqlite outbox lives; workers sharing it share one queue


class DevNullOutboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["devnull"] = "devnull"


class FileOutboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["file"] = "file"
    path: ConfigPath


OutboxConfig = Annotated[SqliteOutboxConfig | DevNullOutboxConfig | FileOutboxConfig, Field(discriminator="kind")]


class Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle: BundleConfig
    secrets: SecretsConfig = Field(default_factory=EnvStoreConfig)  # where provider keys live; must name the store the control plane writes
    events: OutboxConfig = Field(default_factory=DevNullOutboxConfig)
    dev: bool = Field(default=False, validate_default=True)

    @field_validator("dev", mode="before")
    @classmethod
    def dev_from_environment(cls, value: object) -> object:
        configured = os.environ.get("AIRMUX_DEV")
        return configured == "1" if configured is not None else value


def load_config(config_path: str | Path | None = None) -> Config:
    path = Path(config_path or os.environ.get("AIRMUX_CONFIG", "airmux.yml")).resolve()
    section = load_config_section("data_plane", path)
    return Config.model_validate(section, context=ConfigContext(base_dir=path.parent))
