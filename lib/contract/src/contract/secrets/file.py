from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal

from anyio.to_thread import run_sync

from contract.config import ConfigPath
from contract.secrets.base import (
    Secret,
    SecretNotFoundError,
    SecretRejectedError,
    SecretStore,
    SecretStoreConfig,
    SecretStoreUnavailableError,
    path_segments,
)

if TYPE_CHECKING:
    from contract.config import ConfigPath
from contract.secrets.base import SecretRef

DIRECTORY_MODE = 0o700
FILE_MODE = 0o600
DEFAULT_ROOT = Path(".tokkeeper/secrets")


def write_private_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=DIRECTORY_MODE)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".tokkeeper-", dir=path.parent)
        temporary = Path(temporary_name)
        os.fchmod(descriptor, FILE_MODE)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        temporary = None
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()


class FileStoreConfig(SecretStoreConfig):
    kind: Literal["file"] = "file"
    root: ConfigPath = DEFAULT_ROOT

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
        root = self.root.resolve()
        segments = path_segments(ref)
        if any(not segment or segment in {".", ".."} or "/" in segment or "\\" in segment for segment in segments):
            raise SecretRejectedError(self.kind, ref, "secret reference contains an invalid path segment")
        path = root.joinpath(*segments)
        if not path.parent.resolve(strict=False).is_relative_to(root):
            raise SecretRejectedError(self.kind, ref, "secret reference escapes the configured root")
        return path

    async def get(self, ref: SecretRef) -> Secret:
        return await run_sync(self._get, ref)

    def _get(self, ref: SecretRef) -> Secret:
        path = self._path(ref)
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, encoding="utf-8") as handle:
                return Secret(handle.read().strip())
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as e:
            raise SecretNotFoundError(ref) from e
        except OSError as e:
            raise SecretStoreUnavailableError(ref, str(e)) from e

    async def put(self, ref: SecretRef, secret: Secret) -> Secret:
        return await run_sync(self._put, ref, secret)

    def _put(self, ref: SecretRef, secret: Secret) -> Secret:
        path = self._path(ref)
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=DIRECTORY_MODE)
            root = self.root.resolve()
            current = path.parent
            while current.is_relative_to(root):
                current.chmod(DIRECTORY_MODE)
                if current == root:
                    break
                current = current.parent
            write_private_text(path, secret.reveal())
        except OSError as e:
            raise SecretStoreUnavailableError(ref, str(e)) from e
        return secret

    async def delete(self, ref: SecretRef) -> None:
        await run_sync(self._delete, ref)

    def _delete(self, ref: SecretRef) -> None:
        with contextlib.suppress(FileNotFoundError, NotADirectoryError):
            self._path(ref).unlink()
