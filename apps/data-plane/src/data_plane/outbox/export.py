from __future__ import annotations

import logging
import sqlite3
import time
from typing import TYPE_CHECKING

import httpx

from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    from data_plane.outbox.sqlite import SqliteOutbox

logger = logging.getLogger("data_plane")

BATCH_SIZE = 1000


class EventExporter:
    """At-least-once delivery from the durable outbox to the control plane."""

    def __init__(
        self,
        outbox: SqliteOutbox,
        control_plane_url: str,
        control_plane_token: str | None,
        flush_interval_s: float,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._outbox = outbox
        self._url = control_plane_url
        self._token = control_plane_token
        self._flush_interval_s = flush_interval_s
        self._http_client = http_client

    async def once(self) -> int:
        if not self._outbox.claim_export(self._lease_ttl(), time.time()):
            return 0
        events = self._outbox.next_batch(BATCH_SIZE)
        if not events:
            return 0
        response = await self._http_client.post(
            f"{self._url}/v1/events",
            headers={"authorization": f"Bearer {self._token}"},
            json=[event.model_dump(mode="json") for event in events],
        )
        response.raise_for_status()
        self._outbox.acknowledge([str(event.event_id) for event in events])
        return len(events)

    async def run(self) -> None:
        await run_periodic(
            self._export_and_log,
            self._flush_interval_s,
            (httpx.HTTPError, OSError, sqlite3.Error),
            "event export",
        )

    async def _export_and_log(self) -> None:
        sent = await self.once()
        if sent:
            logger.info("exported %d usage events to the control plane", sent)

    def _lease_ttl(self) -> float:
        return max(self._flush_interval_s * 3, 5.0)
