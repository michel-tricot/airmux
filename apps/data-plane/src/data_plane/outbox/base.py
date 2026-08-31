from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio
    from datetime import datetime

    from contract import UsageEventV1


@dataclass(frozen=True)
class OutboxStats:
    pending: int
    oldest_event_at: datetime | None = None


class EventOutbox(ABC):
    """The synchronous request-path sink for metered usage events."""

    @abstractmethod
    def record(self, event: UsageEventV1, /) -> None:
        """Accept one event without network work."""

    def start(self, _task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]:
        return ()

    def close(self) -> None:
        """Release owned resources on shutdown."""
        return

    def stats(self) -> OutboxStats:
        return OutboxStats(pending=0)
