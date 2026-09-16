from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.outbox.base import OUTBOX_CAPACITY, EventOutbox, OutboxStats, ReservationLeakError

if TYPE_CHECKING:
    from contract import UsageEvent


class DevNullOutbox(EventOutbox):
    def __init__(self) -> None:
        super().__init__()

    def record_reserved(self, _event: UsageEvent, /) -> None:
        with self._lock:
            if self._reserved == 0:
                self.fail_invariant("usage event recorded without a reserved outbox slot")
            self._reserved -= 1

    async def stats(self) -> OutboxStats:
        with self._lock:
            return OutboxStats(
                reserved=self._reserved,
                filled=0,
                durable=0,
                capacity=OUTBOX_CAPACITY,
                reservation_rejections=self._reservation_rejections,
                storage_worker_failures=self._storage_worker_failures,
            )

    async def close(self) -> None:
        with self._lock:
            self._accepting = False
            if self._reserved:
                raise ReservationLeakError(self._reserved)
