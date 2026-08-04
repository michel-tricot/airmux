from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from contract import UsageEventV1
    from data_plane.config import Config


def buffer_event(cache_dir: Path, event: UsageEventV1) -> None:
    raise NotImplementedError


def read_buffered_events(cache_dir: Path) -> list[UsageEventV1]:
    raise NotImplementedError


def truncate_buffer(cache_dir: Path) -> None:
    raise NotImplementedError


async def run_flusher(config: Config) -> None:
    raise NotImplementedError
