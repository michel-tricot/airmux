from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.outbox.base import EventOutbox
from data_plane.outbox.devnull import DevNullOutbox
from data_plane.outbox.export import EventExporter
from data_plane.outbox.sqlite import SqliteOutbox

if TYPE_CHECKING:
    import httpx

    from data_plane.config import ControlPlaneLink, EventsConfig

__all__ = ["DevNullOutbox", "EventExporter", "EventOutbox", "SqliteOutbox", "build_exporter", "build_outbox"]


def build_outbox(config: EventsConfig) -> EventOutbox:
    if config.backend == "devnull":
        return DevNullOutbox()
    return SqliteOutbox(cache_dir=config.cache_dir)


def build_exporter(
    outbox: EventOutbox,
    control_plane: ControlPlaneLink,
    events: EventsConfig,
    http_client: httpx.AsyncClient,
) -> EventExporter | None:
    if not isinstance(outbox, SqliteOutbox) or control_plane.url is None:
        return None
    return EventExporter(
        outbox=outbox,
        control_plane_url=control_plane.url,
        control_plane_token=control_plane.token,
        flush_interval_s=events.flush_interval_s,
        http_client=http_client,
    )
