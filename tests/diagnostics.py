from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def retain_logs(directory: Path, destination: Path, filenames: tuple[str, ...], secrets: tuple[str, ...]) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        source = directory / filename
        if source.is_file():
            contents = source.read_text(encoding="utf-8", errors="replace")
            for secret in sorted({secret for secret in secrets if secret}, key=len, reverse=True):
                contents = contents.replace(secret, "[REDACTED]")
            (destination / filename).write_text(contents, encoding="utf-8")
