from __future__ import annotations

import asyncio
import contextvars
from typing import TYPE_CHECKING

from uvicorn.protocols.http.httptools_impl import HttpToolsProtocol

if TYPE_CHECKING:
    from uvicorn._types import ASGI3Application
    from uvicorn.protocols.http.httptools_impl import RequestResponseCycle


class RequestDispatchProtocol(HttpToolsProtocol):
    _pending_requests: list[tuple[RequestResponseCycle, ASGI3Application]] | None = None

    def _start_asgi_task(self, cycle: RequestResponseCycle, app: ASGI3Application) -> None:
        if self._pending_requests is None or self.loop.get_task_factory() is not None or self.limit_concurrency is not None:
            super()._start_asgi_task(cycle, app)
        else:
            self._pending_requests.append((cycle, app))

    def data_received(self, data: bytes) -> None:
        pending_requests: list[tuple[RequestResponseCycle, ASGI3Application]] = []
        self._pending_requests = pending_requests
        try:
            super().data_received(data)
        finally:
            self._pending_requests = None
        for cycle, app in pending_requests:
            context = contextvars.Context() if self.config.reset_contextvars else None
            task = asyncio.Task(cycle.run_asgi(app), loop=self.loop, context=context, eager_start=True)
            task.add_done_callback(self.tasks.discard)
            self.tasks.add(task)
