from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.outbox.base import EventOutbox

if TYPE_CHECKING:
    from contract import UsageEventV1


class DevNullOutbox(EventOutbox):
    """Discards every event. For load tests, local dev, or deployments that meter elsewhere."""

    def record(self, _event: UsageEventV1, /) -> None:
        return
