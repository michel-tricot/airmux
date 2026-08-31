from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx
from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError

from contract import BundleManifest, BundleManifestEntry, SignedBundle, public_key_to_b64, verify_bundle
from data_plane.bundle.base import BundleSource
from data_plane.bundle.holder import BundleSet
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
        self._signed_by_ref: dict[tuple[UUID, UUID], SignedBundle] = {}

    async def once(self) -> None:
        try:
            response = await self._http_client.get(
                f"{self._config.control_plane.url}/api/v1/bundles/manifest",
                headers={"authorization": f"Bearer {self._config.control_plane.token}"},
            )
            response.raise_for_status()
            manifest = BundleManifest.model_validate(response.json()["data"])
            current_refs = tuple(sorted(self._signed_by_ref))
            if _manifest_refs(manifest) != current_refs:
                signed_bundles = list(await asyncio.gather(*(self._resolve(entry) for entry in manifest.bundles)))
                self._adopt(signed_bundles, source="polled", persist=True, expected=manifest.bundles)
        except (InvalidSignature, ValidationError, ValueError) as error:
            self._holder.reject_manifest(str(error))
            raise
        self._holder.accept_manifest()

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
            self._adopt(cached, source="cached", persist=False, expected=None)
        except (InvalidSignature, ValidationError, ValueError):
            logger.exception("cached bundles in %s are invalid, ignoring them", self._config.cache_dir)

    def _adopt(
        self,
        signed_bundles: list[SignedBundle],
        source: str,
        *,
        persist: bool,
        expected: list[BundleManifestEntry] | None,
    ) -> None:
        bundles = tuple(self._verify(signed) for signed in signed_bundles)
        if expected is not None:
            for entry, bundle in zip(expected, bundles, strict=True):
                if (bundle.org_id, bundle.bundle_id) != (entry.org_id, entry.bundle_id):
                    message = (
                        f"bundle {bundle.bundle_id} for org {bundle.org_id} does not match manifest entry {entry.bundle_id} for org {entry.org_id}"
                    )
                    raise ValueError(message)
        bundle_set = BundleSet.from_bundles(bundles)
        if persist:
            write_cached_bundles(self._config.cache_dir, signed_bundles)
        self._holder.swap(bundle_set, source)
        self._signed_by_ref = {(bundle.org_id, bundle.bundle_id): signed for bundle, signed in zip(bundles, signed_bundles, strict=True)}

    async def _resolve(self, entry: BundleManifestEntry) -> SignedBundle:
        existing = self._signed_by_ref.get((entry.org_id, entry.bundle_id))
        if existing is not None:
            return existing
        response = await self._http_client.get(
            f"{self._config.control_plane.url}/api/v1/bundles/{entry.bundle_id}",
            headers={"authorization": f"Bearer {self._config.control_plane.token}"},
        )
        response.raise_for_status()
        return SignedBundle.model_validate(response.json()["data"])

    def _verify(self, signed: SignedBundle) -> BundleV1:
        try:
            return verify_bundle(signed, self._config.verify_key)
        except InvalidSignature as error:
            message = f"bundle signed by {signed.signing_key_id} failed verification with public key {public_key_to_b64(self._config.verify_key)}"
            raise InvalidSignature(message) from error


def _manifest_refs(manifest: BundleManifest) -> tuple[tuple[UUID, UUID], ...]:
    return tuple(sorted((entry.org_id, entry.bundle_id) for entry in manifest.bundles))
