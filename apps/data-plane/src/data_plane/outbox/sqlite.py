from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from pydantic import TypeAdapter

from contract import UsageEvent
from data_plane.outbox.queued import QueuedOutbox
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path

    from data_plane.config import SqliteOutboxConfig
    from data_plane.metrics import DataPlaneMetrics
    from data_plane.outbox.base import OutboxStat

logger = logging.getLogger("data_plane")
USAGE_EVENT_ADAPTER = TypeAdapter(UsageEvent)

BATCH_SIZE = 1000
MAX_BATCHES_PER_FLUSH = 20

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS outbox(event_id TEXT PRIMARY KEY, body TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS flush_lease(id INTEGER PRIMARY KEY CHECK(id = 1), owner TEXT NOT NULL, expires REAL NOT NULL)",
)


@dataclass(frozen=True)
class _DurableBacklog:
    events: int
    oldest_event_at: datetime | None


def _connect(cache_dir: Path) -> sqlite3.Connection:
    cache_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(cache_dir / "events.db"), timeout=5.0)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    for _ in range(100):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                for statement in _SCHEMA:
                    conn.execute(statement)
        except sqlite3.OperationalError:
            time.sleep(0.05)
            continue
        return conn
    conn.close()
    message = f"could not initialize the event outbox in {cache_dir}"
    raise RuntimeError(message)


class SqliteOutbox(QueuedOutbox):
    def __init__(self, config: SqliteOutboxConfig, http_client: httpx.AsyncClient, metrics: DataPlaneMetrics) -> None:
        self._config = config
        self._http_client = http_client
        self._owner = str(os.getpid())
        super().__init__("airmux-sqlite-outbox", metrics)

    def _open_storage(self) -> None:
        self._conn = _connect(self._config.cache_dir)
        self._update_backlog_metrics()

    def _persist(self, events: Sequence[UsageEvent], /) -> None:
        with self._conn:
            self._conn.executemany(
                "INSERT OR IGNORE INTO outbox(event_id, body) VALUES (?, ?)",
                ((str(event.event_id), event.model_dump_json()) for event in events),
            )
        self._update_backlog_metrics()

    def _close_storage(self) -> None:
        self._conn.close()

    def start(self, task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]:
        return (*super().start(task_group), task_group.create_task(self._run_export(), name="event export"))

    def _next_batch(self, limit: int) -> list[UsageEvent]:
        bodies = self._conn.execute("SELECT body FROM outbox ORDER BY rowid LIMIT ?", (limit,)).fetchall()
        return [USAGE_EVENT_ADAPTER.validate_json(body) for (body,) in bodies]

    async def next_batch(self, limit: int, /) -> list[UsageEvent]:
        return await self._storage_call(lambda: self._next_batch(limit))

    def _claim_export(self, ttl: float, now: float) -> bool:
        with self._conn:
            self._conn.execute(
                "INSERT INTO flush_lease(id, owner, expires) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET owner = excluded.owner, expires = excluded.expires "
                "WHERE flush_lease.expires < ? OR flush_lease.owner = excluded.owner",
                (self._owner, now + ttl, now),
            )
            (owner,) = self._conn.execute("SELECT owner FROM flush_lease WHERE id = 1").fetchone()
        return owner == self._owner

    async def claim_export(self, ttl: float, now: float) -> bool:
        return await self._storage_call(lambda: self._claim_export(ttl, now))

    def _acknowledge(self, event_ids: Sequence[str]) -> None:
        with self._conn:
            self._conn.executemany("DELETE FROM outbox WHERE event_id = ?", ((event_id,) for event_id in event_ids))
        self._update_backlog_metrics()

    async def acknowledge(self, event_ids: Sequence[str], /) -> None:
        await self._storage_call(lambda: self._acknowledge(event_ids))

    def _durable_backlog(self) -> _DurableBacklog:
        (events,) = self._conn.execute("SELECT COUNT(*) FROM outbox").fetchone()
        first = self._conn.execute("SELECT body FROM outbox ORDER BY rowid LIMIT 1").fetchone()
        oldest = USAGE_EVENT_ADAPTER.validate_json(first[0]).occurred_at if first is not None else None
        return _DurableBacklog(events=events, oldest_event_at=oldest)

    async def stats(self) -> dict[str, OutboxStat]:
        durable = await self._storage_call(self._durable_backlog)
        return {**self._queue_stats(durable.events, durable.oldest_event_at), "durable": durable.events}

    async def export_once(self) -> int:
        if not await self.claim_export(self._lease_ttl(), time.time()):
            return 0
        events = await self.next_batch(BATCH_SIZE)
        if not events:
            return 0
        started_at = time.monotonic()
        try:
            response = await self._http_client.post(
                f"{self._config.control_plane.url}/api/v1/events",
                headers={"authorization": f"Bearer {self._config.control_plane.management_key}"},
                json=[event.model_dump(mode="json") for event in events],
            )
            response.raise_for_status()
            await self.acknowledge([str(event.event_id) for event in events])
        except (httpx.HTTPError, OSError, sqlite3.Error):
            self._metrics.observe_metering_export("failed", started_at)
            raise
        self._metrics.observe_metering_export("success", started_at)
        return len(events)

    def _update_backlog_metrics(self) -> None:
        backlog = self._durable_backlog()
        self._metrics.set_metering_outbox(backlog.events, backlog.oldest_event_at)

    async def refresh_metrics(self) -> None:
        await self._storage_call(self._update_backlog_metrics)

    async def export_available(self) -> int:
        sent_total = 0
        for _ in range(MAX_BATCHES_PER_FLUSH):
            sent = await self.export_once()
            sent_total += sent
            if sent < BATCH_SIZE:
                break
        return sent_total

    async def _run_export(self) -> None:
        await run_periodic(
            self._export_and_log,
            self._config.flush_interval_s,
            (httpx.HTTPError, OSError, sqlite3.Error),
            "event export",
        )

    async def _export_and_log(self) -> None:
        sent = await self.export_available()
        if sent:
            stats = await self.stats()
            logger.info("exported %d usage events to the control plane, %d remain", sent, stats["durable"])

    def _lease_ttl(self) -> float:
        return max(self._config.flush_interval_s * 3, 5.0)
