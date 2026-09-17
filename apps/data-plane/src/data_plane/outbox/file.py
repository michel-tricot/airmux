from __future__ import annotations

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
        self._event_file = os.open(self._config.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)

    def _persist(self, events: Sequence[UsageEvent], /) -> None:
        body = "".join(event.model_dump_json() + "\n" for event in events).encode()
        if os.write(self._event_file, body) != len(body):
            message = "incomplete event batch write"
            raise OSError(message)

    def _close_storage(self) -> None:
        os.close(self._event_file)
