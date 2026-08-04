from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.outbox.base import EventOutbox
from data_plane.outbox.devnull import DevNullOutbox
from data_plane.outbox.sqlite import SqliteOutbox

if TYPE_CHECKING:
    from data_plane.config import Config

__all__ = ["DevNullOutbox", "EventOutbox", "SqliteOutbox", "build_outbox"]


def build_outbox(config: Config) -> EventOutbox:
    """Pick the event collection backend named in config.events.backend."""
    if config.events.backend == "devnull":
        return DevNullOutbox()
    return SqliteOutbox(config)
