from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Never, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from contract import UsageEvent

OUTBOX_CAPACITY = 10_000

T = TypeVar("T")
type OutboxStat = int | float | None


@dataclass(frozen=True)
class DurableStats:
    events: int = 0
    oldest_event_at: datetime | None = None


class StorageWorkerError(RuntimeError):
    pass


class OutboxClosedError(RuntimeError):
    pass


class ReservationLeakError(RuntimeError):
    def __init__(self, slots: int) -> None:
        super().__init__(f"event outbox closed with {slots} reserved slots")


class OutboxReservation:
    def __init__(self, outbox: QueuedOutbox | None = None) -> None:
        self._outbox = outbox
        self._available = True
        self._released = False

    def record(self, event: UsageEvent, /) -> None:
        if self._released or not self._available:
            self._fail("usage event recorded without a reserved outbox slot")
        if self._outbox is not None:
            self._outbox.record_reserved(event)
        self._available = False

    def release_unused(self) -> None:
        if self._released:
            self._fail("outbox reservation released twice")
        self._released = True
        if self._outbox is not None and self._available:
            self._outbox.release_reserved()
        self._available = False

    def transfer(self) -> OutboxReservation:
        if self._released or not self._available:
            self._fail("outbox reservation transferred without a reserved slot")
        self._available = False
        return OutboxReservation(self._outbox)

    def _fail(self, message: str) -> Never:
        if self._outbox is not None:
            self._outbox.fail_invariant(message)
        error = RuntimeError(message)
        raise error


class EventOutbox(ABC):
    @abstractmethod
    def try_reserve(self) -> OutboxReservation | None:
        pass

    @abstractmethod
    async def stats(self) -> Mapping[str, OutboxStat]:
        pass

    def start(self, _task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]:
        return ()

    @abstractmethod
    async def close(self) -> None:
        pass


class QueuedOutbox(EventOutbox, ABC):
    def __init__(self, thread_name: str) -> None:
        self._lock = threading.RLock()
        self._accepting = True
        self._reserved = 0
        self._filled = 0
        self._reservation_rejections = 0
        self._persisted_events = 0
        self._gracefully_drained_events = 0
        self._storage_worker_failures = 0
        self._failure: BaseException | None = None
        self._events: deque[UsageEvent] = deque()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=thread_name)
        self._drain_scheduled = False
        self._closing = False
        self._failure_signal: tuple[asyncio.AbstractEventLoop, asyncio.Event] | None = None
        try:
            self._executor.submit(self._open_storage).result()
        except BaseException:
            self._executor.shutdown()
            raise

    def try_reserve(self) -> OutboxReservation | None:
        with self._lock:
            if self._failure is not None:
                raise StorageWorkerError from self._failure
            if not self._accepting or self._reserved + self._filled >= OUTBOX_CAPACITY:
                self._reservation_rejections += 1
                return None
            self._reserved += 1
        return OutboxReservation(self)

    def record_reserved(self, event: UsageEvent, /) -> None:
        with self._lock:
            if self._failure is not None:
                raise StorageWorkerError from self._failure
            if self._reserved == 0:
                self.fail_invariant("usage event recorded without a reserved outbox slot")
            self._reserved -= 1
            self._filled += 1
            self._events.append(event)
            self._schedule_drain()

    def release_reserved(self) -> None:
        with self._lock:
            if self._reserved == 0:
                self.fail_invariant("outbox reservation accounting underflow")
            self._reserved -= 1

    def fail_invariant(self, message: str) -> Never:
        error = RuntimeError(message)
        self._fail(error)
        raise error

    def _schedule_drain(self) -> None:
        if self._drain_scheduled or self._closing:
            return
        self._drain_scheduled = True
        future = self._executor.submit(self._persist_one_batch)
        future.add_done_callback(self._drain_finished)

    def _drain_finished(self, future: Future[bool]) -> None:
        error = future.exception()
        if error is not None:
            self._fail(error)
            return
        with self._lock:
            self._drain_scheduled = False
            if self._events:
                self._schedule_drain()

    def _persist_one_batch(self) -> bool:
        with self._lock:
            events = tuple(self._events)
        if not events:
            return False
        self._persist(events)
        with self._lock:
            for _ in events:
                self._events.popleft()
            self._filled -= len(events)
            self._persisted_events += len(events)
            if self._closing:
                self._gracefully_drained_events += len(events)
        return True

    def _fail(self, error: BaseException) -> None:
        with self._lock:
            if self._failure is not None:
                return
            self._failure = error
            self._accepting = False
            self._storage_worker_failures += 1
            target = self._failure_signal
        if target is not None:
            loop, signal = target
            loop.call_soon_threadsafe(signal.set)

    def start(self, task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]:
        loop = asyncio.get_running_loop()
        signal = asyncio.Event()
        with self._lock:
            self._failure_signal = (loop, signal)
            failed = self._failure is not None
        if failed:
            signal.set()
        return (task_group.create_task(self._watch_storage(signal), name="event storage"),)

    async def _watch_storage(self, signal: asyncio.Event) -> None:
        await signal.wait()
        with self._lock:
            error = self._failure
        if error is None:
            raise StorageWorkerError
        raise StorageWorkerError from error

    async def _storage_call(self, operation: Callable[[], T]) -> T:
        with self._lock:
            if self._failure is not None:
                raise StorageWorkerError from self._failure
            if self._closing:
                raise OutboxClosedError
            future = self._executor.submit(operation)
        return await asyncio.wrap_future(future)

    async def stats(self) -> dict[str, int | float | None]:
        durable = await self._storage_call(self._durable_stats)
        with self._lock:
            memory_oldest = self._events[0].occurred_at if self._events else None
            values = tuple(value for value in (memory_oldest, durable.oldest_event_at) if value is not None)
            oldest = min(values) if values else None
            return {
                "reserved": self._reserved,
                "filled": self._filled,
                "durable": durable.events,
                "capacity": OUTBOX_CAPACITY,
                "oldest_age_s": max(0.0, (datetime.now(tz=UTC) - oldest).total_seconds()) if oldest is not None else None,
                "reservation_rejections": self._reservation_rejections,
                "persisted": self._persisted_events,
                "gracefully_drained": self._gracefully_drained_events,
                "storage_worker_failures": self._storage_worker_failures,
            }

    async def close(self) -> None:
        with self._lock:
            self._accepting = False
            self._closing = True
            outstanding = self._reserved
            future = self._executor.submit(self._drain_and_close)
        try:
            await asyncio.wrap_future(future)
        finally:
            self._executor.shutdown()
        if outstanding:
            raise ReservationLeakError(outstanding)
        with self._lock:
            if self._failure is not None:
                raise StorageWorkerError from self._failure

    def _drain_and_close(self) -> None:
        try:
            while self._persist_one_batch():
                pass
        finally:
            self._close_storage()

    @abstractmethod
    def _open_storage(self) -> None:
        pass

    @abstractmethod
    def _persist(self, events: Sequence[UsageEvent], /) -> None:
        pass

    @abstractmethod
    def _durable_stats(self) -> DurableStats:
        pass

    @abstractmethod
    def _close_storage(self) -> None:
        pass
