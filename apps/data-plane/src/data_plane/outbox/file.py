from __future__ import annotations

import fcntl
import os
import threading
from typing import TYPE_CHECKING

from data_plane.outbox.base import EventOutbox

if TYPE_CHECKING:
    from contract import UsageEvent
    from data_plane.config import FileOutboxConfig


class FileOutbox(EventOutbox):
    """Append metered events as immediately readable JSON Lines on a local filesystem."""

    def __init__(self, config: FileOutboxConfig) -> None:
        config.path.parent.mkdir(parents=True, exist_ok=True)
        self._event_file = os.fdopen(os.open(config.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a", encoding="utf-8")
        self._lock = threading.Lock()

    def record(self, event: UsageEvent, /) -> None:
        content = event.model_dump_json() + "\n"
        with self._lock:
            fcntl.flock(self._event_file.fileno(), fcntl.LOCK_EX)
            try:
                self._event_file.write(content)
                self._event_file.flush()
            finally:
                fcntl.flock(self._event_file.fileno(), fcntl.LOCK_UN)

    def close(self) -> None:
        with self._lock:
            self._event_file.close()
