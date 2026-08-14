from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from contract import EnvStoreConfig, SecretsConfig, load_config_section
from data_plane.bundle.config import BundleConfig


class ControlPlaneLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str | None = None  # None means file-only mode, no polling
    token: str | None = None
    heartbeat_interval_s: float = 30.0


class EventsConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    flush_interval_s: float = 5.0
    backend: Literal["sqlite", "devnull"] = "sqlite"  # how usage events are collected; devnull discards them
    cache_dir: Path = Path(".airllm")  # where the sqlite outbox lives; workers sharing it share one queue


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_plane: ControlPlaneLink = Field(default_factory=ControlPlaneLink)
    bundle: BundleConfig
    secrets: SecretsConfig = Field(default_factory=EnvStoreConfig)  # where provider keys live; must name the store the control plane writes
    events: EventsConfig = Field(default_factory=EventsConfig)
    dev: bool = False  # set by the --dev flag on the entry point, gate dev-only behavior on this


def load_config() -> Config:
    section = load_config_section("data_plane")
    return Config.model_validate({**section, "dev": os.environ.get("GW_DEV") == "1"})
