from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from contract import EnvStoreConfig, FileStoreConfig, SecretsConfig, load_config_section
from data_plane.bundle.config import BundleConfig, LocalBundleConfig, RemoteBundleConfig
from data_plane.control_plane_link import ControlPlaneLink


class SqliteOutboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["sqlite"] = "sqlite"
    control_plane: ControlPlaneLink
    flush_interval_s: float = Field(default=5.0, gt=0)
    cache_dir: Path = Path(".tokkeeper")  # where the sqlite outbox lives; workers sharing it share one queue


class DevNullOutboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["devnull"] = "devnull"


OutboxConfig = Annotated[SqliteOutboxConfig | DevNullOutboxConfig, Field(discriminator="kind")]


class Config(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle: BundleConfig
    secrets: SecretsConfig = Field(default_factory=EnvStoreConfig)  # where provider keys live; must name the store the control plane writes
    events: OutboxConfig = Field(default_factory=DevNullOutboxConfig)
    dev: bool = False  # set by the --dev flag on the entry point, gate dev-only behavior on this


def load_config(config_path: str | Path | None = None) -> Config:
    path = Path(config_path or os.environ.get("TOKKEEPER_CONFIG", "tokkeeper.yml")).resolve()
    section = load_config_section("data_plane", path)
    config = Config.model_validate({**section, "dev": os.environ.get("TOKKEEPER_DEV") == "1"})
    bundle = config.bundle
    if isinstance(bundle, LocalBundleConfig):
        bundle = bundle.model_copy(update={"path": path.parent / bundle.path})
    elif isinstance(bundle, RemoteBundleConfig):
        bundle = bundle.model_copy(update={"cache_dir": path.parent / bundle.cache_dir})
    events = config.events
    if isinstance(events, SqliteOutboxConfig):
        events = events.model_copy(update={"cache_dir": path.parent / events.cache_dir})
    secrets = config.secrets
    if isinstance(secrets, FileStoreConfig):
        secrets = secrets.model_copy(update={"root": path.parent / secrets.root})
    return config.model_copy(update={"bundle": bundle, "events": events, "secrets": secrets})
