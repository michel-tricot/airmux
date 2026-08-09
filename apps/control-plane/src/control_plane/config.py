from __future__ import annotations

import os
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contract import Ed25519PrivateKeyB64, load_config_section

if TYPE_CHECKING:
    from pathlib import Path


DEFAULT_DATABASE_URL = "postgresql+asyncpg://airllm:airllm@127.0.0.1:5432/airllm"
"""The local database, for a checkout where the host sets no DATABASE_URL."""


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str = DEFAULT_DATABASE_URL

    @field_validator("url")
    @classmethod
    def names_the_async_driver(cls, url: str) -> str:
        """Managed hosts hand out postgresql:// URLs, and every engine here is async, so asyncpg has to be named.

        Left alone when the URL already names a driver, so an explicitly configured one still wins.
        """
        scheme, separator, rest = url.partition("://")
        return f"postgresql+asyncpg://{rest}" if separator and scheme in {"postgres", "postgresql"} else url


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


def _database(section: dict[str, Any]) -> DatabaseConfig:
    """The database config, treating a ref that resolved to nothing as unset.

    A ${env:DATABASE_URL} the host never set arrives here as None, which is the same situation as
    the key being absent: the default belongs to DatabaseConfig, not to the config file.
    """
    database = section.get("database") or {}
    return DatabaseConfig.model_validate({key: value for key, value in database.items() if value is not None})


def database_url() -> str:
    """The database section alone, for contexts (migrate, alembic env) that have no signing key and cannot build full Settings."""
    return _database(load_config_section("control_plane")).url


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from an explicit config path, falling back to GW_CONFIG for the serve/migrate contexts that pass it via env."""
    section = load_config_section("control_plane", config_path)
    return Settings.model_validate({**section, "database": _database(section), "dev": os.environ.get("GW_DEV") == "1"})
