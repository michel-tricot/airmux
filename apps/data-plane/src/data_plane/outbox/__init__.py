from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.outbox.base import EventOutbox
from data_plane.outbox.devnull import DevNullOutbox
from data_plane.outbox.sqlite import SqliteOutbox

if TYPE_CHECKING:
    import httpx

    from data_plane.config import Config

__all__ = ["DevNullOutbox", "EventOutbox", "SqliteOutbox", "build_outbox"]


def build_outbox(config: Config, http_client: httpx.AsyncClient) -> EventOutbox:
    """Pick the event collection backend named in config.events.backend and hand it only what it needs."""
    if config.events.backend == "devnull":
        return DevNullOutbox()
    return SqliteOutbox(
        cache_dir=config.events.cache_dir,
        control_plane_url=config.control_plane.url,
        control_plane_token=config.control_plane.token,
        flush_interval_s=config.events.flush_interval_s,
        http_client=http_client,
    )
