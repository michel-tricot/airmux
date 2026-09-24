from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import aiohttp
from pydantic import ValidationError

from contract import BundleManifest, BundleManifestEntry, BundleV1
from data_plane.bundle.base import BundleSource
from data_plane.bundle.holder import BundleSet
from data_plane.cache import CachedBundles, read_cached_bundles, write_cached_bundles
from data_plane.cache import instance_id as cache_instance_id
from data_plane.control_plane_link import complete_response
from data_plane.heartbeat import Heartbeat
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    from uuid import UUID

    from data_plane.bundle.config import RemoteBundleConfig
    from data_plane.bundle.holder import BundleHolder

logger = logging.getLogger("data_plane")


class RemoteBundleSource(BundleSource):
    def __init__(
        self,
        config: RemoteBundleConfig,
        holder: BundleHolder,
        http_client: aiohttp.ClientSession,
    ) -> None:
        self._config = config
        self._holder = holder
        self._http_client = http_client
        self._bundles_by_ref: dict[tuple[UUID, UUID], BundleV1] = {}

    async def once(self) -> None:
        changed = False
        try:
            async with self._http_client.get(
                f"{self._config.control_plane.url}/api/v1/bundles/manifest",
                headers={"authorization": f"Bearer {self._config.control_plane.management_key}"},
                allow_redirects=False,
            ) as response:
                await complete_response(response)
                payload = await response.json(content_type=None)
            manifest = BundleManifest.model_validate(payload["data"])
            current_refs = tuple(sorted(self._bundles_by_ref))
            if _manifest_refs(manifest) != current_refs:
                bundles = list(await asyncio.gather(*(self._resolve(entry) for entry in manifest.bundles)))
                self._adopt(bundles, source="polled", persist=True, expected=manifest.bundles)
                changed = True
        except (ValidationError, ValueError):
            self._holder.reject_manifest()
            raise
        except (aiohttp.ClientError, TimeoutError, OSError):
            self._holder.record_poll("failed")
            raise
        if not changed:
            self._holder.record_poll("unchanged")

    async def run(self) -> None:
        await run_periodic(
            self.once,
            self._config.poll_interval_s,
            (aiohttp.ClientError, TimeoutError, ValidationError, OSError, ValueError),
            "bundle poll",
        )

    def start(self, task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]:
        self._load_cached()
        heartbeat = Heartbeat(
            control_plane=self._config.control_plane,
            interval_s=self._config.heartbeat_interval_s,
            holder=self._holder,
            instance_id=cache_instance_id(self._config.cache_dir),
            http_client=self._http_client,
        )
        return (
            task_group.create_task(self.run(), name="bundle poll"),
            task_group.create_task(heartbeat.run(), name="heartbeat"),
        )

    def _load_cached(self) -> None:
        try:
            cached = read_cached_bundles(self._config.cache_dir)
            if cached is None:
                logger.warning("no cached bundles in %s, serving 503 until one arrives", self._config.cache_dir)
                return
            self._adopt(cached.bundles, source="cached", persist=False, expected=None)
        except (ValidationError, ValueError):
            logger.exception("cached bundles in %s are invalid, ignoring them", self._config.cache_dir)

    def _adopt(
        self,
        bundles: list[BundleV1],
        source: str,
        *,
        persist: bool,
        expected: tuple[BundleManifestEntry, ...] | None,
    ) -> None:
        if expected is not None:
            for entry, bundle in zip(expected, bundles, strict=True):
                if (bundle.org_id, bundle.bundle_id) != (entry.org_id, entry.bundle_id):
                    message = (
                        f"bundle {bundle.bundle_id} for org {bundle.org_id} does not match manifest entry {entry.bundle_id} for org {entry.org_id}"
                    )
                    raise ValueError(message)
        bundle_set = BundleSet.from_bundles(tuple(bundles))
        if persist:
            write_cached_bundles(self._config.cache_dir, CachedBundles(bundles=bundles))
        self._holder.swap(bundle_set, source)
        self._bundles_by_ref = {(bundle.org_id, bundle.bundle_id): bundle for bundle in bundles}

    async def _resolve(self, entry: BundleManifestEntry) -> BundleV1:
        existing = self._bundles_by_ref.get((entry.org_id, entry.bundle_id))
        if existing is not None:
            return existing
        async with self._http_client.get(
            f"{self._config.control_plane.url}/api/v1/bundles/{entry.bundle_id}",
            headers={"authorization": f"Bearer {self._config.control_plane.management_key}"},
            allow_redirects=False,
        ) as response:
            await complete_response(response)
            payload = await response.json(content_type=None)
        return BundleV1.model_validate(payload["data"])


def _manifest_refs(manifest: BundleManifest) -> tuple[tuple[UUID, UUID], ...]:
    return tuple(sorted((entry.org_id, entry.bundle_id) for entry in manifest.bundles))
