from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator

from contract import EnvStoreConfig, SecretsConfig, load_config_section
from contract.config import ConfigContext
from control_plane.keys import validate_management_key_token
from control_plane.throttling import ThrottleConfig

DEFAULT_DATABASE_URL = "postgresql+asyncpg://airmux:airmux@127.0.0.1:5432/airmux"
"""The local database, for a checkout where the host sets no DATABASE_URL."""

DEFAULT_CONSOLE_URL = "http://127.0.0.1:5000"
"""Where the console is served in a checkout; compose sets AIRMUX_CONSOLE_URL to the port nginx publishes."""


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = DEFAULT_DATABASE_URL

    @field_validator("url")
    @classmethod
    def names_the_async_driver(cls, url: str) -> str:
        """Managed hosts hand out postgresql:// URLs, and every engine here is async, so asyncpg has to be named.

        Left alone when the URL already names a driver, so an explicitly configured one still wins.
        """
        scheme, separator, rest = url.partition("://")
        return f"postgresql+asyncpg://{rest}" if separator and scheme in {"postgres", "postgresql"} else url


class DataPlaneBootstrap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token: SecretStr

    @field_validator("token")
    @classmethod
    def valid_management_key(cls, token: SecretStr) -> SecretStr:
        validate_management_key_token(token.get_secret_value())
        return token


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    throttling: ThrottleConfig = Field(default_factory=ThrottleConfig)
    bootstrap: DataPlaneBootstrap | None = None
    secrets: SecretsConfig = Field(default_factory=EnvStoreConfig)  # where provider keys live; the data plane must name the same store

    console_url: str = DEFAULT_CONSOLE_URL  # where the console is served; device-flow verification URLs are built from it
    public_signup: bool = False

    @field_validator("console_url")
    @classmethod
    def console_origin(cls, value: str) -> str:
        url = HttpUrl(value)
        if url.path not in {None, "/"} or url.query is not None or url.fragment is not None or url.username is not None:
            message = "console_url must be an HTTP or HTTPS origin without a path, query, fragment, or credentials"
            raise ValueError(message)
        return str(url).rstrip("/")


def database_url() -> str:
    """Load the database section alone for migration contexts that do not need full settings."""
    section = load_config_section("control_plane")
    return DatabaseConfig.model_validate(section.get("database") or {}).url


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from an explicit config path, falling back to AIRMUX_CONFIG for the serve/migrate contexts that pass it via env."""
    path = Path(config_path or os.environ.get("AIRMUX_CONFIG", "airmux.yml")).resolve()
    section = load_config_section("control_plane", path)
    return Settings.model_validate(section, context=ConfigContext(base_dir=path.parent))
