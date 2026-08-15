from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

import httpx

from contract import HeartbeatV1
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    from uuid import UUID

    from data_plane.bundle.holder import BundleHolder
    from data_plane.config import Config

try:
    VERSION = version("data-plane")
except PackageNotFoundError:  # pragma: no cover - only when running from a non-installed tree
    VERSION = "unknown"


async def heartbeat_once(config: Config, holder: BundleHolder, instance_id: UUID, http_client: httpx.AsyncClient) -> None:
    snapshot = holder.snapshot
    body = HeartbeatV1(instance_id=instance_id, version=VERSION, bundle_id=snapshot.bundle.bundle_id if snapshot else None)
    resp = await http_client.post(
        f"{config.control_plane.url}/v1/heartbeat",
        headers={"authorization": f"Bearer {config.control_plane.token}"},
        json=body.model_dump(mode="json"),
    )
    resp.raise_for_status()


async def run_heartbeat(config: Config, holder: BundleHolder, instance_id: UUID, http_client: httpx.AsyncClient) -> None:
    await run_periodic(
        lambda: heartbeat_once(config, holder, instance_id, http_client),
        config.control_plane.heartbeat_interval_s,
        (httpx.HTTPError, OSError),
        "heartbeat",
    )
