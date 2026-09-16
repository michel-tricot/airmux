from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

GENERATED_STATE_GITIGNORE = "*.key\ngateway/\nsecrets/\n"
DIRECTORY_MODE = 0o700
FILE_MODE = 0o600


def write_private_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=DIRECTORY_MODE)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".airmux-", dir=path.parent)
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


def write_new_configuration(directory: Path, files: Mapping[str, str]) -> None:
    for name in files:
        path = directory / name
        if path.exists() or path.is_symlink():
            message = f"{path} already exists; choose another directory"
            raise FileExistsError(message)
    directory.mkdir(parents=True, exist_ok=True, mode=DIRECTORY_MODE)
    created: list[Path] = []
    try:
        for name, contents in files.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True, mode=DIRECTORY_MODE)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
            created.append(path)
            with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
                destination.write(contents)
    except OSError:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
