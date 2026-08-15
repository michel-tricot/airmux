from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError

from contract import SignedBundle, public_key_to_b64, verify_bundle
from data_plane.bundle.base import BundleSource
from data_plane.cache import instance_id as cache_instance_id
from data_plane.cache import read_cached_bundle, write_cached_bundle
from data_plane.heartbeat import Heartbeat
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    import asyncio

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

    async def once(self) -> None:
        response = await self._http_client.get(
            f"{self._config.control_plane.url}/v1/bundle/latest",
            headers={"authorization": f"Bearer {self._config.control_plane.token}"},
            params={"org_id": str(self._config.org)} if self._config.org else {},
        )
        response.raise_for_status()
        signed = SignedBundle.model_validate(response.json()["data"])
        if self._holder.snapshot is not None and signed.payload.bundle_id == self._holder.snapshot.bundle.bundle_id:
            return
        try:
            bundle = verify_bundle(signed, self._config.verify_key)
        except InvalidSignature as error:
            message = (
                f"bundle {signed.payload.bundle_id} signed by {signed.signing_key_id} for org {signed.payload.org_id} "
                f"failed verification with public key {public_key_to_b64(self._config.verify_key)}"
            )
            raise InvalidSignature(message) from error
        if self._holder.admit(bundle, self._config.staleness_policy, source="polled"):
            write_cached_bundle(self._config.cache_dir, signed)

    async def run(self) -> None:
        await run_periodic(
            self.once,
            self._config.poll_interval_s,
            (httpx.HTTPError, ValidationError, InvalidSignature, OSError),
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
            signed = read_cached_bundle(self._config.cache_dir)
        except ValidationError:
            logger.exception("cached bundle in %s does not parse, ignoring it", self._config.cache_dir)
            return
        if signed is None:
            logger.warning("no cached bundle in %s, serving 503 until one arrives", self._config.cache_dir)
            return
        try:
            bundle = verify_bundle(signed, self._config.verify_key)
        except InvalidSignature:
            logger.exception("cached bundle failed signature verification, ignoring it")
            return
        self._holder.admit(bundle, self._config.staleness_policy, source="cached")
