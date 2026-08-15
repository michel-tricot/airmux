from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import TYPE_CHECKING

import httpx

from contract import UsageEventV1
from data_plane.outbox.base import EventOutbox
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Sequence
    from pathlib import Path

    from data_plane.config import SqliteOutboxConfig

logger = logging.getLogger("data_plane")

BATCH_SIZE = 1000

# A durable event queue backed by SQLite in WAL mode. Many data plane processes may share one cache
# dir: SQLite serializes their writes, so every worker records into the same queue and a single
# leaseholder exports it. Deletes are keyed on event_id, so even a redundant export can neither lose
# nor double-drop an event, unlike a positional file buffer.

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS outbox(event_id TEXT PRIMARY KEY, body TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS flush_lease(id INTEGER PRIMARY KEY CHECK(id = 1), owner TEXT NOT NULL, expires REAL NOT NULL)",
)


def _connect(cache_dir: Path) -> sqlite3.Connection:
    cache_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(cache_dir / "events.db"), timeout=5.0)
    conn.execute("PRAGMA busy_timeout=5000")  # a writer waits for the lock rather than raising under contention
    conn.execute("PRAGMA synchronous=NORMAL")  # durable across an app crash, fast; only a power loss can drop the last commit
    # The WAL switch and first schema create take a brief exclusive lock that busy_timeout does not cover, so
    # several fresh workers starting at once contend; retry until the first one wins and the rest see WAL already set.
    for _ in range(100):
        try:
            conn.execute("PRAGMA journal_mode=WAL")  # readers never block the writer; safe for multiple processes on one host
            with conn:
                for statement in _SCHEMA:
                    conn.execute(statement)
        except sqlite3.OperationalError:
            time.sleep(0.05)
            continue
        return conn
    conn.close()
    msg = f"could not initialize the event outbox in {cache_dir}"
    raise RuntimeError(msg)


class SqliteOutbox(EventOutbox):
    """Durable, multi-writer event queue with single-exporter leasing."""

    def __init__(
        self,
        config: SqliteOutboxConfig,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._conn = _connect(config.cache_dir)
        self._owner = str(os.getpid())
        self._config = config
        self._http_client = http_client

    def record(self, event: UsageEventV1, /) -> None:
        with self._conn:
            self._conn.execute("INSERT OR IGNORE INTO outbox(event_id, body) VALUES (?, ?)", (str(event.event_id), event.model_dump_json()))

    def close(self) -> None:
        self._conn.close()

    def start(self, task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]:
        return (task_group.create_task(self._run_export(), name="event export"),)

    def next_batch(self, limit: int, /) -> list[UsageEventV1]:
        rows = self._conn.execute("SELECT body FROM outbox ORDER BY rowid LIMIT ?", (limit,)).fetchall()
        return [UsageEventV1.model_validate_json(body) for (body,) in rows]

    def claim_export(self, ttl: float, now: float) -> bool:
        """Win or renew the export lease, which another worker can take after expiry."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO flush_lease(id, owner, expires) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET owner = excluded.owner, expires = excluded.expires "
                "WHERE flush_lease.expires < ? OR flush_lease.owner = excluded.owner",
                (self._owner, now + ttl, now),
            )
            (owner,) = self._conn.execute("SELECT owner FROM flush_lease WHERE id = 1").fetchone()
        return owner == self._owner

    def acknowledge(self, event_ids: Sequence[str], /) -> None:
        with self._conn:
            self._conn.executemany("DELETE FROM outbox WHERE event_id = ?", [(event_id,) for event_id in event_ids])

    async def export_once(self) -> int:
        if not self.claim_export(self._lease_ttl(), time.time()):
            return 0
        events = self.next_batch(BATCH_SIZE)
        if not events:
            return 0
        response = await self._http_client.post(
            f"{self._config.control_plane.url}/v1/events",
            headers={"authorization": f"Bearer {self._config.control_plane.token}"},
            json=[event.model_dump(mode="json") for event in events],
        )
        response.raise_for_status()
        self.acknowledge([str(event.event_id) for event in events])
        return len(events)

    async def _run_export(self) -> None:
        await run_periodic(
            self._export_and_log,
            self._config.flush_interval_s,
            (httpx.HTTPError, OSError, sqlite3.Error),
            "event export",
        )

    async def _export_and_log(self) -> None:
        sent = await self.export_once()
        if sent:
            logger.info("exported %d usage events to the control plane", sent)

    def _lease_ttl(self) -> float:
        return max(self._config.flush_interval_s * 3, 5.0)
