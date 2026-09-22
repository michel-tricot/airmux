from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

import aiohttp

from contract import HeartbeatV1
from data_plane.control_plane_link import complete_response
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    from uuid import UUID

    from data_plane.bundle.holder import BundleHolder
    from data_plane.control_plane_link import ControlPlaneLink

try:
    VERSION = version("airmux")
except PackageNotFoundError:  # pragma: no cover - only when running from a non-installed tree
    VERSION = "unknown"


class Heartbeat:
    def __init__(
        self,
        control_plane: ControlPlaneLink,
        interval_s: float,
        holder: BundleHolder,
        instance_id: UUID,
        http_client: aiohttp.ClientSession,
    ) -> None:
        self._control_plane = control_plane
        self._interval_s = interval_s
        self._holder = holder
        self._instance_id = instance_id
        self._http_client = http_client

    async def once(self) -> None:
        snapshots = tuple(self._holder.current.snapshots.values())
        body = HeartbeatV1(
            instance_id=self._instance_id,
            version=VERSION,
            bundle_id=snapshots[0].bundle.bundle_id if len(snapshots) == 1 else None,
        )
        async with self._http_client.post(
            f"{self._control_plane.url}/api/v1/heartbeat",
            headers={"authorization": f"Bearer {self._control_plane.management_key}"},
            json=body.model_dump(mode="json"),
            allow_redirects=False,
        ) as response:
            await complete_response(response)

    async def run(self) -> None:
        await run_periodic(
            self.once,
            self._interval_s,
            (aiohttp.ClientError, TimeoutError, OSError),
            "heartbeat",
        )
