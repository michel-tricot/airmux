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
    from collections.abc import Sequence
    from pathlib import Path

logger = logging.getLogger("data_plane")

BATCH = 1000

# A durable event queue backed by SQLite in WAL mode. Many data plane processes may share one cache
# dir: SQLite serializes their writes, so every worker records into the same queue and a single
# leaseholder flushes it. Deletes are keyed on event_id, so even a redundant flush can neither lose
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
    """Durable, multi-writer event queue with single-flusher leasing, flushed to the control plane."""

    def __init__(self, cache_dir: Path, control_plane_url: str | None, control_plane_token: str | None, flush_interval_s: float) -> None:
        self._conn = _connect(cache_dir)
        self._owner = str(os.getpid())
        self._url = control_plane_url
        self._token = control_plane_token
        self._flush_interval_s = flush_interval_s

    def record(self, event: UsageEventV1) -> None:
        with self._conn:
            self._conn.execute("INSERT OR IGNORE INTO outbox(event_id, body) VALUES (?, ?)", (str(event.event_id), event.model_dump_json()))

    async def run(self, http_client: httpx.AsyncClient) -> None:
        if not self._url:
            return

        async def once() -> None:
            sent = await self._flush(http_client)
            if sent:
                logger.info("flushed %d usage events to the control plane", sent)

        await run_periodic(once, self._flush_interval_s, (httpx.HTTPError, OSError, sqlite3.Error), "event flush")

    def close(self) -> None:
        self._conn.close()

    async def _flush(self, http_client: httpx.AsyncClient) -> int:
        """At-least-once delivery: only the leaseholder sends, then deletes exactly what it sent; the CP dedups on event_id."""
        if not self._url or not self._claim_flush(self._lease_ttl(), time.time()):
            return 0
        events = self._read_batch(BATCH)
        if not events:
            return 0
        resp = await http_client.post(
            f"{self._url}/v1/events",
            headers={"authorization": f"Bearer {self._token}"},
            json=[e.model_dump(mode="json") for e in events],
        )
        resp.raise_for_status()
        self._delete([str(e.event_id) for e in events])
        return len(events)

    def _read_batch(self, limit: int) -> list[UsageEventV1]:
        rows = self._conn.execute("SELECT body FROM outbox ORDER BY rowid LIMIT ?", (limit,)).fetchall()
        return [UsageEventV1.model_validate_json(body) for (body,) in rows]

    def _pending(self) -> int:
        (count,) = self._conn.execute("SELECT COUNT(*) FROM outbox").fetchone()
        return int(count)

    def _claim_flush(self, ttl: float, now: float) -> bool:
        """Win or renew the single flush lease. A dead holder's lease expires, so another worker takes over."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO flush_lease(id, owner, expires) VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET owner = excluded.owner, expires = excluded.expires "
                "WHERE flush_lease.expires < ? OR flush_lease.owner = excluded.owner",
                (self._owner, now + ttl, now),
            )
            (owner,) = self._conn.execute("SELECT owner FROM flush_lease WHERE id = 1").fetchone()
        return owner == self._owner

    def _delete(self, event_ids: Sequence[str]) -> None:
        with self._conn:
            self._conn.executemany("DELETE FROM outbox WHERE event_id = ?", [(event_id,) for event_id in event_ids])

    def _lease_ttl(self) -> float:
        """Outlast a few flush intervals so the holder renews before expiry, but fail over quickly if it dies."""
        return max(self._flush_interval_s * 3, 5.0)
