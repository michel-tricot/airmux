from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError

from contract import SignedBundle, public_key_to_b64, verify_bundle
from data_plane.cache import write_cached_bundle
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    from data_plane.bundle.config import RemoteBundleConfig
    from data_plane.bundle.holder import BundleHolder
    from data_plane.config import ControlPlaneLink


class BundlePoller:
    def __init__(
        self,
        link: ControlPlaneLink,
        config: RemoteBundleConfig,
        holder: BundleHolder,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._link = link
        self._config = config
        self._holder = holder
        self._http_client = http_client

    async def once(self) -> None:
        response = await self._http_client.get(
            f"{self._link.url}/v1/bundle/latest",
            headers={"authorization": f"Bearer {self._link.token}"},
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
