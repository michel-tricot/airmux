from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from contract import (
    ACCESS_KEY_PREFIX,
    Ed25519PrivateKeyB64,
    EnvStoreConfig,
    SecretsConfig,
    load_config_section,
)

DEFAULT_DATABASE_URL = "postgresql+asyncpg://airllm:airllm@127.0.0.1:5432/airllm"
"""The local database, for a checkout where the host sets no DATABASE_URL."""

DEFAULT_CONSOLE_URL = "http://127.0.0.1:5000"
"""Where the console is served in a checkout; compose sets GW_CONSOLE_URL to the port nginx publishes."""

MIN_ACCESS_KEY_SECRET_LENGTH = 32
MAX_ACCESS_KEY_LENGTH = 512


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


class FileDataPlaneBootstrap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["file"] = "file"
    path: Path


def validate_data_plane_token(value: str) -> str:
    if (
        not value.startswith(ACCESS_KEY_PREFIX)
        or len(value) < len(ACCESS_KEY_PREFIX) + MIN_ACCESS_KEY_SECRET_LENGTH
        or len(value) > MAX_ACCESS_KEY_LENGTH
    ):
        msg = "bootstrap token must be a complete access key"
        raise ValueError(msg)
    return value


class TokenDataPlaneBootstrap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["token"] = "token"
    token: SecretStr

    @field_validator("token")
    @classmethod
    def valid_access_key(cls, token: SecretStr) -> SecretStr:
        validate_data_plane_token(token.get_secret_value())
        return token


DataPlaneBootstrap = Annotated[FileDataPlaneBootstrap | TokenDataPlaneBootstrap, Field(discriminator="kind")]


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    bundle: BundlePolicy
    bootstrap: DataPlaneBootstrap | None = None
    secrets: SecretsConfig = Field(default_factory=EnvStoreConfig)  # where provider keys live; the data plane must name the same store

    console_url: str = DEFAULT_CONSOLE_URL  # where the console is served; device-flow verification URLs are built from it


def database_url() -> str:
    """The database section alone, for contexts (migrate, alembic env) that have no signing key and cannot build full Settings."""
    section = load_config_section("control_plane")
    return DatabaseConfig.model_validate(section.get("database") or {}).url


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from an explicit config path, falling back to GW_CONFIG for the serve/migrate contexts that pass it via env."""
    section = load_config_section("control_plane", config_path)
    return Settings.model_validate(section)
