from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal

from contract.secrets.base import Secret, SecretNotFoundError, SecretStore, SecretStoreConfig, SecretStoreUnavailableError, path_segments

if TYPE_CHECKING:
    from contract.secrets.base import SecretRef

DIRECTORY_MODE = 0o700
FILE_MODE = 0o600
DEFAULT_ROOT = Path(".airllm/secrets")


class FileStoreConfig(SecretStoreConfig):
    kind: Literal["file"] = "file"
    root: Path = DEFAULT_ROOT

    def build(self) -> FileSecretStore:
        return FileSecretStore(root=self.root)


class FileSecretStore(SecretStore):
    """One file per credential under a root directory, owner-readable only.

    The deployment this fits is a single host with a mounted secrets volume: real enough to run on,
    small enough to need no service. The root belongs on a volume that is not backed up into
    anything a bundle or a log reaches.
    """

    kind: ClassVar[str] = "file"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, ref: SecretRef) -> Path:
        return self.root.joinpath(*path_segments(ref))

    async def get(self, ref: SecretRef) -> Secret:
        path = self._path(ref)
        try:
            return Secret(path.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as e:
            raise SecretNotFoundError(ref) from e
        except OSError as e:
            raise SecretStoreUnavailableError(ref, str(e)) from e

    async def put(self, ref: SecretRef, secret: Secret) -> Secret:
        path = self._path(ref)
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=DIRECTORY_MODE)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
        except OSError as e:
            raise SecretStoreUnavailableError(ref, str(e)) from e
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(descriptor, FILE_MODE)  # O_CREAT's mode applies only to a file this call created
            handle.write(secret.reveal())
        return secret

    async def delete(self, ref: SecretRef) -> None:
        with contextlib.suppress(FileNotFoundError, NotADirectoryError):
            self._path(ref).unlink()
