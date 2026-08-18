from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx
from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError

from contract import BundleManifest, BundleManifestEntry, SignedBundle, public_key_to_b64, verify_bundle
from data_plane.bundle.base import BundleSource
from data_plane.cache import instance_id as cache_instance_id
from data_plane.cache import read_cached_bundles, write_cached_bundles
from data_plane.heartbeat import Heartbeat
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    from uuid import UUID

    from contract import BundleV1
    from data_plane.bundle.config import RemoteBundleConfig
    from data_plane.bundle.holder import BundleHolder

logger = logging.getLogger("data_plane")


class BundleManifestMismatchError(ValueError):
    pass


class RemoteBundleSource(BundleSource):
    def __init__(
        self,
        config: RemoteBundleConfig,
        holder: BundleHolder,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._holder = holder
        self._http_client = http_client
        self._signed_by_org: dict[UUID, SignedBundle] = {}

    async def once(self) -> None:
        response = await self._http_client.get(
            f"{self._config.control_plane.url}/api/v1/bundles/manifest",
            headers={"authorization": f"Bearer {self._config.control_plane.token}"},
        )
        response.raise_for_status()
        manifest = BundleManifest.model_validate(response.json()["data"])
        current = tuple(sorted((org_id, signed.payload.bundle_id) for org_id, signed in self._signed_by_org.items()))
        if _bundle_ids(manifest) == current:
            return
        signed_bundles = list(await asyncio.gather(*(self._resolve(entry) for entry in manifest.bundles)))
        bundles = tuple(self._verify(signed) for signed in signed_bundles)
        current = self._holder.prepare(bundles)
        write_cached_bundles(self._config.cache_dir, signed_bundles)
        self._holder.publish(current, source="polled")
        self._signed_by_org = {signed.payload.org_id: signed for signed in signed_bundles}

    async def run(self) -> None:
        await run_periodic(
            self.once,
            self._config.poll_interval_s,
            (httpx.HTTPError, ValidationError, InvalidSignature, OSError, ValueError),
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
            bundles = tuple(self._verify(signed) for signed in cached.bundles)
            self._holder.replace(bundles, source="cached")
        except (InvalidSignature, ValidationError, ValueError):
            logger.exception("cached bundles in %s are invalid, ignoring them", self._config.cache_dir)
            return
        self._signed_by_org = {signed.payload.org_id: signed for signed in cached.bundles}

    async def _resolve(self, entry: BundleManifestEntry) -> SignedBundle:
        existing = self._signed_by_org.get(entry.org_id)
        if existing is not None and existing.payload.bundle_id == entry.bundle_id:
            return existing
        response = await self._http_client.get(
            f"{self._config.control_plane.url}/api/v1/bundles/{entry.bundle_id}",
            headers={"authorization": f"Bearer {self._config.control_plane.token}"},
        )
        response.raise_for_status()
        signed = SignedBundle.model_validate(response.json()["data"])
        if (signed.payload.org_id, signed.payload.bundle_id) != (entry.org_id, entry.bundle_id):
            raise BundleManifestMismatchError
        return signed

    def _verify(self, signed: SignedBundle) -> BundleV1:
        try:
            return verify_bundle(signed, self._config.verify_key)
        except InvalidSignature as error:
            message = (
                f"bundle {signed.payload.bundle_id} signed by {signed.signing_key_id} for org {signed.payload.org_id} "
                f"failed verification with public key {public_key_to_b64(self._config.verify_key)}"
            )
            raise InvalidSignature(message) from error


def _bundle_ids(manifest: BundleManifest) -> tuple[tuple[UUID, UUID], ...]:
    return tuple(sorted((entry.org_id, entry.bundle_id) for entry in manifest.bundles))
