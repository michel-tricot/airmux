from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def write_new_configuration(directory: Path, files: Mapping[str, str]) -> None:
    for name in files:
        path = directory / name
        if path.exists() or path.is_symlink():
            message = f"{path} already exists; choose another directory"
            raise FileExistsError(message)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    created: list[Path] = []
    try:
        for name, contents in files.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
                destination.write(contents)
    except OSError:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
