from __future__ import annotations

from typing import Annotated

from pydantic import Field

from contract.secrets.base import (
    OrgSecretRef,
    PlatformSecretRef,
    Secret,
    SecretNotFoundError,
    SecretPurpose,
    SecretRef,
    SecretReference,
    SecretRejectedError,
    SecretStore,
    SecretStoreConfig,
    SecretStoreUnavailableError,
    WorkspaceSecretRef,
)
from contract.secrets.env import EnvSecretStore, EnvStoreConfig
from contract.secrets.file import FileSecretStore, FileStoreConfig
from contract.secrets.insecure_database import InsecureDatabaseSecretStore, InsecureDatabaseStoreConfig
from contract.secrets.memory import MemorySecretStore, MemoryStoreConfig

SecretsConfig = Annotated[MemoryStoreConfig | FileStoreConfig | EnvStoreConfig | InsecureDatabaseStoreConfig, Field(discriminator="kind")]
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
    "InsecureDatabaseSecretStore",
    "InsecureDatabaseStoreConfig",
    "MemorySecretStore",
    "MemoryStoreConfig",
    "OrgSecretRef",
    "PlatformSecretRef",
    "Secret",
    "SecretNotFoundError",
    "SecretPurpose",
    "SecretRef",
    "SecretReference",
    "SecretRejectedError",
    "SecretStore",
    "SecretStoreConfig",
    "SecretStoreUnavailableError",
    "SecretsConfig",
    "WorkspaceSecretRef",
]
