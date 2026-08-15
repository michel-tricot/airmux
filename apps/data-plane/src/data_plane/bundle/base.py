from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio


class BundleSource(ABC):
    @abstractmethod
    def start(self, task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]: ...
