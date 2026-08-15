from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.config import DevNullOutboxConfig
from data_plane.outbox.base import EventOutbox
from data_plane.outbox.devnull import DevNullOutbox
from data_plane.outbox.sqlite import SqliteOutbox

if TYPE_CHECKING:
    import httpx

    from data_plane.config import ControlPlaneLink, OutboxConfig

__all__ = ["DevNullOutbox", "EventOutbox", "SqliteOutbox", "build_outbox"]


def build_outbox(config: OutboxConfig, control_plane: ControlPlaneLink, http_client: httpx.AsyncClient) -> EventOutbox:
    if isinstance(config, DevNullOutboxConfig):
        return DevNullOutbox()
    if not control_plane.url:
        msg = "sqlite event outbox requires a control-plane URL"
        raise ValueError(msg)
    return SqliteOutbox(
        cache_dir=config.cache_dir,
        control_plane_url=control_plane.url,
        control_plane_token=control_plane.token,
        flush_interval_s=config.flush_interval_s,
        http_client=http_client,
    )
