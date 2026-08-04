from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError

from contract import SignedBundle, verify_bundle
from data_plane.auth import index_keys
from data_plane.cache import write_cached_bundle
from data_plane.transport import client

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from data_plane.config import Config
    from data_plane.holder import BundleHolder

logger = logging.getLogger("data_plane")


async def poll_once(config: Config, holder: BundleHolder, public_key: Ed25519PublicKey) -> None:
    resp = await client.get(f"{config.control_plane_url}/v1/bundle/latest", headers={"authorization": f"Bearer {config.dp_token}"})
    resp.raise_for_status()
    signed = SignedBundle.model_validate_json(resp.content)
    bundle = verify_bundle(signed, public_key)
    if holder.current is not None and bundle.bundle_id == holder.current.bundle_id:
        return
    if bundle.expires_at <= datetime.now(tz=UTC) and config.staleness_policy == "refuse":
        logger.warning("polled bundle %s already expired at %s, refusing per policy", bundle.bundle_id, bundle.expires_at)
        return
    holder.swap(bundle, index_keys(bundle))
    write_cached_bundle(config.cache_dir, signed)
    logger.info("swapped to bundle %s issued %s", bundle.bundle_id, bundle.issued_at)


async def run_poller(config: Config, holder: BundleHolder, public_key: Ed25519PublicKey) -> None:
    while True:
        try:
            await poll_once(config, holder, public_key)
        except (httpx.HTTPError, ValidationError, InvalidSignature, OSError):
            logger.exception("bundle poll failed, keeping current bundle")
        await asyncio.sleep(config.poll_interval_s)
