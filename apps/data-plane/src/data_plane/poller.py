from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from data_plane.config import Config
    from data_plane.holder import BundleHolder


async def poll_once(config: Config, holder: BundleHolder) -> None:
    raise NotImplementedError


async def run_poller(config: Config, holder: BundleHolder) -> None:
    raise NotImplementedError
