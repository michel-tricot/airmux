from __future__ import annotations

from data_plane.outbox.base import EventOutbox, OutboxReservation


class DevNullOutbox(EventOutbox):
    def try_reserve(self) -> OutboxReservation:
        return OutboxReservation()

    async def stats(self) -> dict[str, int | float | None]:
        return {}

    async def close(self) -> None:
        pass
