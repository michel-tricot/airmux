from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio

    from contract import UsageEventV1


class EventOutbox(ABC):
    """The synchronous request-path sink for metered usage events."""

    @abstractmethod
    def record(self, event: UsageEventV1, /) -> None:
        """Accept one event without network work."""

    def start(self) -> tuple[asyncio.Task[None], ...]:
        return ()

    def close(self) -> None:
        """Release owned resources on shutdown."""
        return
