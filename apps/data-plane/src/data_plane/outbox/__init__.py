from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.config import DevNullOutboxConfig, FileOutboxConfig
from data_plane.outbox.base import EventOutbox, OutboxFullError, OutboxReservation
from data_plane.outbox.devnull import DevNullOutbox
from data_plane.outbox.file import FileOutbox
from data_plane.outbox.sqlite import SqliteOutbox

if TYPE_CHECKING:
    import httpx2

    from data_plane.config import OutboxConfig
    from data_plane.metrics import DataPlaneMetrics

__all__ = ["DevNullOutbox", "EventOutbox", "FileOutbox", "OutboxFullError", "OutboxReservation", "SqliteOutbox", "build_outbox"]


def build_outbox(config: OutboxConfig, http_client: httpx2.AsyncClient, metrics: DataPlaneMetrics) -> EventOutbox:
    if isinstance(config, DevNullOutboxConfig):
        return DevNullOutbox(metrics)
    if isinstance(config, FileOutboxConfig):
        return FileOutbox(config, metrics)
    return SqliteOutbox(config, http_client, metrics)
