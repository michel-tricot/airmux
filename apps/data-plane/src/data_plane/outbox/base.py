from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from contract import UsageEvent

OUTBOX_CAPACITY = 1024
STORAGE_BATCH_SIZE = 1000

T = TypeVar("T")


@dataclass(frozen=True)
class DurableStats:
    events: int = 0
    oldest_event_at: datetime | None = None


@dataclass(frozen=True)
class OutboxStats:
    reserved: int
    filled: int
    durable: int
    capacity: int
    oldest_event_at: datetime | None = None
    reservation_rejections: int = 0
    persisted_events: int = 0
    gracefully_drained_events: int = 0
    storage_worker_failures: int = 0


class StorageWorkerError(RuntimeError):
    pass


class OutboxClosedError(RuntimeError):
    pass


class ReservationLeakError(RuntimeError):
    def __init__(self, slots: int) -> None:
        super().__init__(f"event outbox closed with {slots} reserved slots")


class OutboxReservation:
    def __init__(self, outbox: EventOutbox, slots: int) -> None:
        self._outbox = outbox
        self._remaining = slots
        self._released = False
        self._lock = threading.Lock()

    def record(self, event: UsageEvent, /) -> None:
        with self._lock:
            if self._released or self._remaining == 0:
                self._outbox.fail_invariant("usage event recorded without a reserved outbox slot")
            self._outbox.record_reserved(event)
            self._remaining -= 1

    def release_unused(self) -> None:
        with self._lock:
            if self._released:
                self._outbox.fail_invariant("outbox reservation released twice")
            self._released = True
            self._outbox.release_reserved(self._remaining)
            self._remaining = 0


class EventOutbox(ABC):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._accepting = True
        self._reserved = 0
        self._filled = 0
        self._reservation_rejections = 0
        self._persisted_events = 0
        self._gracefully_drained_events = 0
        self._storage_worker_failures = 0
        self._failure: BaseException | None = None

    def try_reserve(self, slots: int, /) -> OutboxReservation | None:
        if slots < 0:
            self.fail_invariant("outbox reservation size cannot be negative")
        with self._lock:
            if self._failure is not None:
                raise StorageWorkerError from self._failure
            if not self._accepting or self._reserved + self._filled + slots > OUTBOX_CAPACITY:
                self._reservation_rejections += 1
                return None
            self._reserved += slots
        return OutboxReservation(self, slots)

    @abstractmethod
    def record_reserved(self, event: UsageEvent, /) -> None:
        pass

    def release_reserved(self, slots: int, /) -> None:
        with self._lock:
            if slots > self._reserved:
                self.fail_invariant("outbox reservation accounting underflow")
            self._reserved -= slots

    def fail_invariant(self, message: str) -> None:
        error = RuntimeError(message)
        self._fail(error)
        raise error

    def _fail(self, error: BaseException) -> None:
        with self._lock:
            if self._failure is not None:
                return
            self._failure = error
            self._accepting = False
            self._storage_worker_failures += 1

    @abstractmethod
    async def stats(self) -> OutboxStats:
        pass

    def start(self, _task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]:
        return ()

    @abstractmethod
    async def close(self) -> None:
        pass


class QueuedOutbox(EventOutbox, ABC):
    def __init__(self, thread_name: str) -> None:
        super().__init__()
        self._events: deque[UsageEvent] = deque()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=thread_name)
        self._drain_scheduled = False
        self._closing = False
        self._failure_signals: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []
        try:
            self._executor.submit(self._open_storage).result()
        except BaseException:
            self._executor.shutdown()
            raise

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
            events = tuple(list(self._events)[:STORAGE_BATCH_SIZE])
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
        super()._fail(error)
        with self._lock:
            signals = tuple(self._failure_signals)
        for loop, signal in signals:
            loop.call_soon_threadsafe(signal.set)

    def start(self, task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]:
        loop = asyncio.get_running_loop()
        signal = asyncio.Event()
        with self._lock:
            self._failure_signals.append((loop, signal))
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

    async def stats(self) -> OutboxStats:
        durable = await self._storage_call(self._durable_stats)
        with self._lock:
            memory_oldest = self._events[0].occurred_at if self._events else None
            values = tuple(value for value in (memory_oldest, durable.oldest_event_at) if value is not None)
            return OutboxStats(
                reserved=self._reserved,
                filled=self._filled,
                durable=durable.events,
                capacity=OUTBOX_CAPACITY,
                oldest_event_at=min(values) if values else None,
                reservation_rejections=self._reservation_rejections,
                persisted_events=self._persisted_events,
                gracefully_drained_events=self._gracefully_drained_events,
                storage_worker_failures=self._storage_worker_failures,
            )

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
