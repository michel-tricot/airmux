from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

import httpx

from data_plane.tasks import run_periodic
from data_plane.transport import client

if TYPE_CHECKING:
    from data_plane.config import Config
    from data_plane.outbox import Outbox

logger = logging.getLogger("data_plane")

BATCH = 1000


def _lease_ttl(config: Config) -> float:
    """Outlast a few flush intervals so the holder renews before expiry, but fail over quickly if it dies."""
    return max(config.events.flush_interval_s * 3, 5.0)


async def flush_once(config: Config, outbox: Outbox) -> int:
    """At-least-once delivery: only the leaseholder sends, then deletes exactly what it sent; the CP dedups on event_id."""
    if not config.control_plane.url or not outbox.claim_flush(_lease_ttl(config)):
        return 0
    events = outbox.read_batch(BATCH)
    if not events:
        return 0
    resp = await client.post(
        f"{config.control_plane.url}/v1/events",
        headers={"authorization": f"Bearer {config.control_plane.token}"},
        json=[e.model_dump(mode="json") for e in events],
    )
    resp.raise_for_status()
    outbox.delete([str(e.event_id) for e in events])
    return len(events)


async def run_flusher(config: Config, outbox: Outbox) -> None:
    async def once() -> None:
        sent = await flush_once(config, outbox)
        if sent:
            logger.info("flushed %d usage events to the control plane", sent)

    await run_periodic(once, config.events.flush_interval_s, (httpx.HTTPError, OSError, sqlite3.Error), "event flush")
