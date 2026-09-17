from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.config import DevNullOutboxConfig, FileOutboxConfig
from data_plane.outbox.base import EventOutbox, OutboxFullError, OutboxReservation
from data_plane.outbox.devnull import DevNullOutbox
from data_plane.outbox.file import FileOutbox
from data_plane.outbox.sqlite import SqliteOutbox

if TYPE_CHECKING:
    import httpx

    from data_plane.config import OutboxConfig

__all__ = ["DevNullOutbox", "EventOutbox", "FileOutbox", "OutboxFullError", "OutboxReservation", "SqliteOutbox", "build_outbox"]


def build_outbox(config: OutboxConfig, http_client: httpx.AsyncClient) -> EventOutbox:
    if isinstance(config, DevNullOutboxConfig):
        return DevNullOutbox()
    if isinstance(config, FileOutboxConfig):
        return FileOutbox(config)
    return SqliteOutbox(config, http_client)
