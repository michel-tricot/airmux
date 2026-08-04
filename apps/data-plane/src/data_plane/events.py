from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from pydantic import ValidationError

from contract import UsageEventV1
from data_plane.cache import atomic_write_text
from data_plane.tasks import run_periodic
from data_plane.transport import client

if TYPE_CHECKING:
    from pathlib import Path

    from data_plane.config import Config

logger = logging.getLogger("data_plane")


def _buffer_path(cache_dir: Path) -> Path:
    return cache_dir / "events.jsonl"


def _lines(path: Path) -> list[str]:
    """The one definition of the buffer's line format; every reader and rewriter goes through it."""
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def buffer_event(cache_dir: Path, event: UsageEventV1) -> None:
    with _buffer_path(cache_dir).open("a", encoding="utf-8") as f:
        f.write(event.model_dump_json() + "\n")


def read_buffered_events(cache_dir: Path) -> list[UsageEventV1]:
    return [UsageEventV1.model_validate_json(line) for line in _lines(_buffer_path(cache_dir))]


def _read_repairing(cache_dir: Path) -> list[UsageEventV1]:
    """Read for flushing, healing what a crash can leave behind.

    A torn final line (killed mid-append) is dropped with a warning; corruption
    anywhere else quarantines the whole buffer instead of wedging the flusher.
    After repair the file holds exactly the returned events, so _drop_first
    line counting stays aligned.
    """
    path = _buffer_path(cache_dir)
    lines = _lines(path)
    events: list[UsageEventV1] = []
    for i, line in enumerate(lines):
        try:
            events.append(UsageEventV1.model_validate_json(line))
        except ValidationError:
            if i == len(lines) - 1:
                logger.warning("dropping torn final line in the event buffer, likely a crash during append")
                atomic_write_text(path, "".join(line + "\n" for line in lines[:i]))
                return events
            quarantine = path.with_suffix(".jsonl.corrupt")
            path.replace(quarantine)
            logger.exception("event buffer corrupt at line %d, quarantined to %s", i + 1, quarantine)
            return []
    return events


def _drop_first(cache_dir: Path, count: int) -> None:
    path = _buffer_path(cache_dir)
    atomic_write_text(path, "".join(line + "\n" for line in _lines(path)[count:]))


async def flush_once(config: Config) -> int:
    """At-least-once delivery: send the batch, then drop exactly what was sent; the CP dedups on event_id."""
    events = _read_repairing(config.bundle.cache_dir)
    if not events or not config.control_plane.url:
        return 0
    resp = await client.post(
        f"{config.control_plane.url}/v1/events",
        headers={"authorization": f"Bearer {config.control_plane.token}"},
        json=[e.model_dump(mode="json") for e in events],
    )
    resp.raise_for_status()
    _drop_first(config.bundle.cache_dir, len(events))
    return len(events)


async def run_flusher(config: Config) -> None:
    async def once() -> None:
        sent = await flush_once(config)
        if sent:
            logger.info("flushed %d usage events to the control plane", sent)

    await run_periodic(once, config.events.flush_interval_s, (httpx.HTTPError, OSError, ValueError), "event flush")
