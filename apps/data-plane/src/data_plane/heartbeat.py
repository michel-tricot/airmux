from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

import httpx

from contract import HeartbeatV1
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    from uuid import UUID

    from data_plane.bundle.holder import BundleHolder
    from data_plane.config import ControlPlaneLink

try:
    VERSION = version("data-plane")
except PackageNotFoundError:  # pragma: no cover - only when running from a non-installed tree
    VERSION = "unknown"


class Heartbeat:
    def __init__(
        self,
        config: ControlPlaneLink,
        holder: BundleHolder,
        instance_id: UUID,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._holder = holder
        self._instance_id = instance_id
        self._http_client = http_client

    async def once(self) -> None:
        snapshot = self._holder.snapshot
        body = HeartbeatV1(
            instance_id=self._instance_id,
            version=VERSION,
            bundle_id=snapshot.bundle.bundle_id if snapshot else None,
        )
        response = await self._http_client.post(
            f"{self._config.url}/v1/heartbeat",
            headers={"authorization": f"Bearer {self._config.token}"},
            json=body.model_dump(mode="json"),
        )
        response.raise_for_status()

    async def run(self) -> None:
        await run_periodic(
            self.once,
            self._config.heartbeat_interval_s,
            (httpx.HTTPError, OSError),
            "heartbeat",
        )
