from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.outbox.base import EventOutbox

if TYPE_CHECKING:
    from contract import IngestEvent


class DevNullOutbox(EventOutbox):
    def _record_reserved(self, _event: IngestEvent, /) -> None:
        pass
