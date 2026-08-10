from __future__ import annotations

from typing import Annotated

from pydantic import Field

from contract.secrets.base import (
    Secret,
    SecretNotFoundError,
    SecretPurpose,
    SecretRef,
    SecretRejectedError,
    SecretStore,
    SecretStoreConfig,
    SecretStoreUnavailableError,
)
from contract.secrets.env import EnvSecretStore, EnvStoreConfig
from contract.secrets.file import FileSecretStore, FileStoreConfig
from contract.secrets.memory import MemorySecretStore, MemoryStoreConfig

SecretsConfig = Annotated[MemoryStoreConfig | FileStoreConfig | EnvStoreConfig, Field(discriminator="kind")]
"""Which store this process talks to, tagged by kind so each backend parses only its own settings.

Both planes read their own copy of this section and must name the same store, because one writes
what the other reads. `config.build()` is how either plane gets its store; there is no factory to
edit when a backend is added.
"""

__all__ = [
    "EnvSecretStore",
    "EnvStoreConfig",
    "FileSecretStore",
    "FileStoreConfig",
    "MemorySecretStore",
    "MemoryStoreConfig",
    "Secret",
    "SecretNotFoundError",
    "SecretPurpose",
    "SecretRef",
    "SecretRejectedError",
    "SecretStore",
    "SecretStoreConfig",
    "SecretStoreUnavailableError",
    "SecretsConfig",
]
