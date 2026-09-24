from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

UVICORN_LISTENER = re.compile(r"Uvicorn running on http://127\.0\.0\.1:(\d+)")


def uvicorn_port(log_path: Path) -> int | None:
    if not log_path.exists():
        return None
    match = UVICORN_LISTENER.search(log_path.read_text(encoding="utf-8"))
    return int(match.group(1)) if match else None
