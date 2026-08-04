from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger("data_plane")


async def run_periodic(once: Callable[[], Awaitable[object]], interval_s: float, recoverable: tuple[type[Exception], ...], name: str) -> None:
    """The one background-loop shell: recoverable failures log and retry, everything else escapes."""
    while True:
        try:
            await once()
        except recoverable:
            logger.exception("%s failed, will retry", name)
        await asyncio.sleep(interval_s)
