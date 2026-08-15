from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx

    from contract import UsageEventV1


class EventOutbox(ABC):
    """Where usage events go after metering: the plug point for how the data plane collects them.

    record() sits on the request hot path, so it must not await or block on the network; do any
    durable or remote work in run(), the background loop started once per process for the app's
    lifetime. A backend that needs no background work returns from run() immediately.
    """

    @abstractmethod
    def record(self, event: UsageEventV1) -> None:
        """Accept one event. Called inline while serving a request."""

    async def run(self, http_client: httpx.AsyncClient) -> None:  # noqa: ARG002 backends with no export work do not use HTTP
        """Background export loop; runs until cancelled. The default does nothing, for backends with no background work."""
        return

    def close(self) -> None:
        """Release resources on shutdown. The default does nothing."""
        return
