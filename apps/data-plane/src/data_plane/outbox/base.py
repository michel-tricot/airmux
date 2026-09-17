from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Never, Self

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable, Mapping
    from types import TracebackType

    from contract import UsageEvent

type OutboxStat = int | float | None


class OutboxFullError(RuntimeError):
    pass


class OutboxReservation:
    def __init__(
        self,
        record: Callable[[UsageEvent], None],
        release: Callable[[], None],
        fail: Callable[[str], None],
    ) -> None:
        self._record = record
        self._release = release
        self._fail_reservation = fail
        self._available = True
        self._closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _error_type: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if self._closed:
            self._fail("outbox reservation released twice")
        self._closed = True
        if self._available:
            self._release()
            self._available = False

    def record(self, event: UsageEvent, /) -> None:
        if self._closed or not self._available:
            self._fail("usage event recorded without a reserved outbox slot")
        self._record(event)
        self._available = False

    def transfer(self) -> OutboxReservation:
        if self._closed or not self._available:
            self._fail("outbox reservation transferred without a reserved slot")
        self._available = False
        return OutboxReservation(self._record, self._release, self._fail_reservation)

    def _fail(self, message: str) -> Never:
        self._fail_reservation(message)
        raise RuntimeError(message)


class EventOutbox(ABC):
    def reserve(self) -> OutboxReservation:
        self._reserve()
        return OutboxReservation(self._record_reserved, self._release_reserved, self._fail_reservation)

    def _reserve(self) -> None:
        return None

    @abstractmethod
    def _record_reserved(self, event: UsageEvent, /) -> None:
        pass

    def _release_reserved(self) -> None:
        return None

    def _fail_reservation(self, message: str) -> None:
        raise RuntimeError(message)

    async def stats(self) -> Mapping[str, OutboxStat]:
        return {}

    def start(self, _task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]:
        return ()

    async def close(self) -> None:
        return None
