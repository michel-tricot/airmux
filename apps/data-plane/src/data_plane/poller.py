from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError

from contract import SignedBundle, verify_bundle
from data_plane.cache import write_cached_bundle
from data_plane.tasks import run_periodic
from data_plane.transport import client

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from data_plane.config import Config
    from data_plane.holder import BundleHolder

logger = logging.getLogger("data_plane")


async def poll_once(config: Config, holder: BundleHolder, public_key: Ed25519PublicKey) -> None:
    resp = await client.get(
        f"{config.control_plane.url}/v1/bundle/latest",
        headers={"authorization": f"Bearer {config.control_plane.token}"},
        params={"org_id": config.bundle.org} if config.bundle.org else {},
    )
    resp.raise_for_status()
    signed = SignedBundle.model_validate(resp.json()["data"])
    if holder.snapshot is not None and signed.payload.bundle_id == holder.snapshot.bundle.bundle_id:
        return
    bundle = verify_bundle(signed, public_key)
    if holder.admit(bundle, config.bundle.staleness_policy, source="polled"):
        write_cached_bundle(config.bundle.cache_dir, signed)


async def run_poller(config: Config, holder: BundleHolder, public_key: Ed25519PublicKey) -> None:
    await run_periodic(
        lambda: poll_once(config, holder, public_key),
        config.bundle.poll_interval_s,
        (httpx.HTTPError, ValidationError, InvalidSignature, OSError),
        "bundle poll",
    )
