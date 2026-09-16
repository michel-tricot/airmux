from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import ClassVar, Literal

from anyio.to_thread import run_sync

from airmux_runtime.config import ConfigPath  # noqa: TC001 pydantic resolves the model field annotation at runtime
from airmux_runtime.files import DIRECTORY_MODE, write_private_text
from airmux_runtime.secrets.base import (
    Secret,
    SecretNotFoundError,
    SecretRef,
    SecretRejectedError,
    SecretStoreConfig,
    SecretStoreUnavailableError,
    _SecretAdapter,
    path_segments,
)

DEFAULT_PATH = Path(".airmux/secrets")


class FileStoreConfig(SecretStoreConfig):
    kind: Literal["file"] = "file"
    path: ConfigPath = DEFAULT_PATH

    def build(self) -> FileSecretStore:
        return FileSecretStore(path=self.path)


class FileSecretStore(_SecretAdapter):
    kind: ClassVar[str] = "file"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _path(self, ref: SecretRef) -> Path:
        root = self.path.resolve()
        segments = path_segments(ref)
        if any(not segment or segment in {".", ".."} or "/" in segment or "\\" in segment for segment in segments):
            raise SecretRejectedError(self.kind, ref, "secret reference contains an invalid path segment")
        path = root.joinpath(*segments)
        if not path.parent.resolve(strict=False).is_relative_to(root):
            raise SecretRejectedError(self.kind, ref, "secret reference escapes the configured path")
        return path

    async def get(self, ref: SecretRef) -> Secret:
        return await run_sync(self._get, ref)

    def _get(self, ref: SecretRef) -> Secret:
        path = self._path(ref)
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, encoding="utf-8") as handle:
                return Secret(handle.read().strip())
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError) as error:
            raise SecretNotFoundError(ref) from error
        except OSError as error:
            raise SecretStoreUnavailableError(ref, str(error)) from error

    async def put(self, ref: SecretRef, secret: Secret) -> None:
        await run_sync(self._put, ref, secret)

    def _put(self, ref: SecretRef, secret: Secret) -> None:
        path = self._path(ref)
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=DIRECTORY_MODE)
            root = self.path.resolve()
            current = path.parent
            while current.is_relative_to(root):
                current.chmod(DIRECTORY_MODE)
                if current == root:
                    break
                current = current.parent
            write_private_text(path, secret.reveal())
        except OSError as error:
            raise SecretStoreUnavailableError(ref, str(error)) from error

    async def delete(self, ref: SecretRef) -> None:
        await run_sync(self._delete, ref)

    def _delete(self, ref: SecretRef) -> None:
        with contextlib.suppress(FileNotFoundError, NotADirectoryError):
            self._path(ref).unlink()
