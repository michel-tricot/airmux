from __future__ import annotations

import asyncio
import logging
import threading
from abc import abstractmethod
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Never, TypeVar

from airmux_runtime.observability import log_event
from data_plane.outbox.base import EventOutbox, OutboxClosedError, OutboxFullError, OutboxStat

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from contract import UsageEvent
    from data_plane.metrics import DataPlaneMetrics

CAPACITY = 10_000

T = TypeVar("T")
logger = logging.getLogger("data_plane")


class _StorageWorkerError(RuntimeError):
    pass


class _OutboxClosedError(RuntimeError):
    pass


class _ReservationLeakError(RuntimeError):
    def __init__(self, slots: int) -> None:
        super().__init__(f"event outbox closed with {slots} reserved slots")


class QueuedOutbox(EventOutbox):
    def __init__(self, thread_name: str, metrics: DataPlaneMetrics) -> None:
        super().__init__(metrics)
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
        self._update_queue_metrics()

    def _reserve(self) -> None:
        with self._lock:
            if self._failure is not None:
                raise _StorageWorkerError from self._failure
            if not self._accepting:
                self._reservation_rejections += 1
                raise OutboxClosedError
            if self._reserved + self._filled >= CAPACITY:
                self._reservation_rejections += 1
                raise OutboxFullError
            self._reserved += 1
            self._update_queue_metrics()

    @property
    def accepting(self) -> bool:
        with self._lock:
            return self._failure is None and self._accepting and self._reserved + self._filled < CAPACITY

    def _record_reserved(self, event: UsageEvent, /) -> None:
        with self._lock:
            if self._failure is not None:
                raise _StorageWorkerError from self._failure
            if self._reserved == 0:
                self._fail_reservation("usage event recorded without a reserved outbox slot")
            self._reserved -= 1
            self._filled += 1
            self._events.append(event)
            self._update_queue_metrics()
            self._schedule_drain()

    def _release_reserved(self) -> None:
        with self._lock:
            if self._reserved == 0:
                self._fail_reservation("outbox reservation accounting underflow")
            self._reserved -= 1
            self._update_queue_metrics()

    def _fail_reservation(self, message: str) -> Never:
        error = RuntimeError(message)
        self._fail(error)
        raise error

    def _schedule_drain(self) -> None:
        if self._drain_scheduled or self._closing:
            return
        self._drain_scheduled = True
        future = self._executor.submit(self._persist_queued)
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

    def _persist_queued(self) -> bool:
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
            self._update_queue_metrics()
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
            raise _StorageWorkerError
        raise _StorageWorkerError from error

    async def _storage_call(self, operation: Callable[[], T]) -> T:
        with self._lock:
            if self._failure is not None:
                raise _StorageWorkerError from self._failure
            if self._closing:
                raise _OutboxClosedError
            future = self._executor.submit(operation)
        return await asyncio.wrap_future(future)

    def _queue_stats(self, stored: int = 0, stored_oldest: datetime | None = None) -> dict[str, OutboxStat]:
        with self._lock:
            memory_oldest = self._events[0].occurred_at if self._events else None
            values = tuple(value for value in (memory_oldest, stored_oldest) if value is not None)
            oldest = min(values) if values else None
            return {
                "pending": self._reserved + self._filled + stored,
                "reserved": self._reserved,
                "filled": self._filled,
                "capacity": CAPACITY,
                "oldest_age_s": max(0.0, (datetime.now(tz=UTC) - oldest).total_seconds()) if oldest is not None else None,
                "reservation_rejections": self._reservation_rejections,
                "persisted": self._persisted_events,
                "gracefully_drained": self._gracefully_drained_events,
                "storage_worker_failures": self._storage_worker_failures,
            }

    async def stats(self) -> Mapping[str, OutboxStat]:
        return self._queue_stats()

    async def close(self) -> None:
        outcome = "failed"
        with self._lock:
            self._accepting = False
            self._closing = True
            outstanding = self._reserved
            future = self._executor.submit(self._drain_and_close)
        try:
            try:
                await asyncio.wrap_future(future)
            finally:
                self._executor.shutdown()
            if outstanding:
                raise _ReservationLeakError(outstanding)
            with self._lock:
                if self._failure is not None:
                    raise _StorageWorkerError from self._failure
            outcome = "success"
        finally:
            log_event(logger, logging.INFO if outcome == "success" else logging.ERROR, "metering_shutdown_drain", outcome=outcome)

    def _update_queue_metrics(self) -> None:
        self._metrics.set_metering_queue(self._reserved + self._filled, CAPACITY)

    def _drain_and_close(self) -> None:
        try:
            while self._persist_queued():
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
    def _close_storage(self) -> None:
        pass
