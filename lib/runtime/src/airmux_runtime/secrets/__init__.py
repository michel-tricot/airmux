from __future__ import annotations

from typing import Annotated

from pydantic import Field

from airmux_runtime.secrets.base import (
    Secret,
    SecretNotFoundError,
    SecretReader,
    SecretRejectedError,
    SecretStore,
    SecretStoreConfig,
    SecretStoreUnavailableError,
)
from airmux_runtime.secrets.env import EnvSecretStore, EnvStoreConfig
from airmux_runtime.secrets.file import FileSecretStore, FileStoreConfig
from airmux_runtime.secrets.insecure_database import InsecureDatabaseSecretStore, InsecureDatabaseStoreConfig
from airmux_runtime.secrets.memory import MemorySecretStore, MemoryStoreConfig

SecretsConfig = Annotated[FileStoreConfig | EnvStoreConfig | InsecureDatabaseStoreConfig, Field(discriminator="kind")]

__all__ = [
    "EnvSecretStore",
    "EnvStoreConfig",
    "FileSecretStore",
    "FileStoreConfig",
    "InsecureDatabaseSecretStore",
    "InsecureDatabaseStoreConfig",
    "MemorySecretStore",
    "MemoryStoreConfig",
    "Secret",
    "SecretNotFoundError",
    "SecretReader",
    "SecretRejectedError",
    "SecretStore",
    "SecretStoreConfig",
    "SecretStoreUnavailableError",
    "SecretsConfig",
]
