from __future__ import annotations

import os
from datetime import timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from contract import Ed25519PrivateKeyB64, load_config_section

if TYPE_CHECKING:
    from pathlib import Path


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str = "postgresql+asyncpg://airllm:airllm@127.0.0.1:5432/airllm"


class BundlePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    signing_key: Ed25519PrivateKeyB64  # parsed once from base64 at load; signs bundles
    staleness_bound_hours: float = 24.0

    @property
    def staleness_bound(self) -> timedelta:
        return timedelta(hours=self.staleness_bound_hours)


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    bundle: BundlePolicy
    console_url: str = "http://127.0.0.1:5000"  # where the console is served; device-flow verification URLs are built from it
    dev: bool = False  # set by the --dev flag on the entry point, gate dev-only behavior on this


def database_url() -> str:
    """The database section alone, for contexts (migrate, alembic env) that have no signing key and cannot build full Settings."""
    section = load_config_section("control_plane")
    return DatabaseConfig.model_validate(section.get("database") or {}).url


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from an explicit config path, falling back to GW_CONFIG for the serve/migrate contexts that pass it via env."""
    section = load_config_section("control_plane", config_path)
    return Settings.model_validate({**section, "dev": os.environ.get("GW_DEV") == "1"})
