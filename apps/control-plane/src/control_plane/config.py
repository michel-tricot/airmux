from __future__ import annotations

from ipaddress import ip_address
from typing import TYPE_CHECKING, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from contract import EnvStoreConfig, SecretsConfig, load_config_section
from control_plane.keys import validate_access_key_token

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_DATABASE_URL = "postgresql+asyncpg://airllm:airllm@127.0.0.1:5432/airllm"
"""The local database, for a checkout where the host sets no DATABASE_URL."""

DEFAULT_CONSOLE_URL = "http://127.0.0.1:5000"
"""Where the console is served in a checkout; compose sets AIRLLM_CONSOLE_URL to the port nginx publishes."""

MIN_CLAIM_TOKEN_LENGTH = 32


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


class DataPlaneBootstrap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token: SecretStr

    @field_validator("token")
    @classmethod
    def valid_access_key(cls, token: SecretStr) -> SecretStr:
        validate_access_key_token(token.get_secret_value())
        return token


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    bootstrap: DataPlaneBootstrap | None = None
    secrets: SecretsConfig = Field(default_factory=EnvStoreConfig)  # where provider keys live; the data plane must name the same store

    console_url: str = DEFAULT_CONSOLE_URL  # where the console is served; device-flow verification URLs are built from it
    claim_token: SecretStr | None = None

    @field_validator("claim_token", mode="before")
    @classmethod
    def normalize_claim_token(cls, token: object) -> object:
        return token or None

    @field_validator("claim_token")
    @classmethod
    def validate_claim_token(cls, token: SecretStr | None) -> SecretStr | None:
        if token is not None and len(token.get_secret_value()) < MIN_CLAIM_TOKEN_LENGTH:
            message = f"claim token must contain at least {MIN_CLAIM_TOKEN_LENGTH} characters"
            raise ValueError(message)
        return token

    @model_validator(mode="after")
    def protect_public_claim(self) -> Self:
        hostname = urlsplit(self.console_url).hostname
        local = hostname == "localhost"
        if hostname is not None and not local:
            try:
                local = ip_address(hostname).is_loopback
            except ValueError:
                local = False
        if not local and self.claim_token is None:
            message = "a public console URL requires a claim token in AIRLLM_CLAIM_TOKEN"
            raise ValueError(message)
        return self


def database_url() -> str:
    """Load the database section alone for migration contexts that do not need full settings."""
    section = load_config_section("control_plane")
    return DatabaseConfig.model_validate(section.get("database") or {}).url


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load settings from an explicit config path, falling back to AIRLLM_CONFIG for the serve/migrate contexts that pass it via env."""
    section = load_config_section("control_plane", config_path)
    return Settings.model_validate(section)
