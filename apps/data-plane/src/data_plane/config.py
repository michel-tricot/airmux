from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from contract import EnvStoreConfig, SecretsConfig, load_config_section
from contract.config import ConfigContext, ConfigPath
from data_plane.bundle.config import BundleConfig
from data_plane.control_plane_link import ControlPlaneLink


class SqliteOutboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["sqlite"] = "sqlite"
    control_plane: ControlPlaneLink
    flush_interval_s: float = Field(default=5.0, gt=0)
    cache_dir: ConfigPath = Path(".tokkeeper")  # where the sqlite outbox lives; workers sharing it share one queue


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
    dev: bool = False  # set by the --dev flag on the entry point, gate dev-only behavior on this


def load_config(config_path: str | Path | None = None) -> Config:
    path = Path(config_path or os.environ.get("TOKKEEPER_CONFIG", "tokkeeper.yml")).resolve()
    section = load_config_section("data_plane", path)
    return Config.model_validate({**section, "dev": os.environ.get("TOKKEEPER_DEV") == "1"}, context=ConfigContext(base_dir=path.parent))
