from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from contract import Ed25519PublicKeyB64, load_config_section


class ControlPlaneLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str | None = None  # None means file-only mode, no polling
    token: str | None = None
    heartbeat_interval_s: float = 30.0


class BundleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    public_key: Ed25519PublicKeyB64  # parsed once from base64 at load; verifies bundle signatures
    org: UUID | None = None  # which org's bundle this data plane serves; None takes the newest across orgs
    cache_dir: Path = Path("/var/cache/gateway")
    staleness_policy: Literal["serve_and_warn", "refuse"] = "serve_and_warn"
    poll_interval_s: float = 30.0


class EventsConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    flush_interval_s: float = 5.0
    backend: Literal["sqlite", "devnull"] = "sqlite"  # how usage events are collected; devnull discards them


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    control_plane: ControlPlaneLink = Field(default_factory=ControlPlaneLink)
    bundle: BundleConfig
    events: EventsConfig = Field(default_factory=EventsConfig)
    dev: bool = False  # set by the --dev flag on the entry point, gate dev-only behavior on this


def load_config() -> Config:
    section = load_config_section("data_plane")
    return Config.model_validate({**section, "dev": os.environ.get("GW_DEV") == "1"})
