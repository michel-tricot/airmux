from __future__ import annotations

import fcntl
import os
from typing import TYPE_CHECKING

from data_plane.outbox.queued import QueuedOutbox

if TYPE_CHECKING:
    from collections.abc import Sequence

    from contract import UsageEvent
    from data_plane.config import FileOutboxConfig


class FileOutbox(QueuedOutbox):
    def __init__(self, config: FileOutboxConfig) -> None:
        self._config = config
        super().__init__("airmux-file-outbox")

    def _open_storage(self) -> None:
        self._config.path.parent.mkdir(parents=True, exist_ok=True)
        self._event_file = os.fdopen(os.open(self._config.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "a", encoding="utf-8")

    def _persist(self, events: Sequence[UsageEvent], /) -> None:
        fcntl.flock(self._event_file.fileno(), fcntl.LOCK_EX)
        try:
            self._event_file.writelines(event.model_dump_json() + "\n" for event in events)
            self._event_file.flush()
        finally:
            fcntl.flock(self._event_file.fileno(), fcntl.LOCK_UN)

    def _close_storage(self) -> None:
        self._event_file.close()
