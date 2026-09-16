from __future__ import annotations

from data_plane.outbox.base import EventOutbox, OutboxReservation


class DevNullOutbox(EventOutbox):
    def try_reserve(self, slots: int, /) -> OutboxReservation:
        if slots < 0:
            message = "outbox reservation size cannot be negative"
            raise RuntimeError(message)
        return OutboxReservation(slots)

    async def stats(self) -> dict[str, int | float | None]:
        return {}

    async def close(self) -> None:
        pass
