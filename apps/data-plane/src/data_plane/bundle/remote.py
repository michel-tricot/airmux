from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError

from contract import SignedBundle, public_key_to_b64, verify_bundle
from data_plane.cache import write_cached_bundle
from data_plane.tasks import run_periodic
from data_plane.transport import client

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from data_plane.bundle.config import RemoteBundleConfig
    from data_plane.bundle.holder import BundleHolder
    from data_plane.config import ControlPlaneLink

logger = logging.getLogger("data_plane")


async def poll_once(link: ControlPlaneLink, bundle_config: RemoteBundleConfig, holder: BundleHolder, public_key: Ed25519PublicKey) -> None:
    resp = await client.get(
        f"{link.url}/v1/bundle/latest",
        headers={"authorization": f"Bearer {link.token}"},
        params={"org_id": str(bundle_config.org)} if bundle_config.org else {},
    )
    resp.raise_for_status()
    signed = SignedBundle.model_validate(resp.json()["data"])
    if holder.snapshot is not None and signed.payload.bundle_id == holder.snapshot.bundle.bundle_id:
        return
    try:
        bundle = verify_bundle(signed, public_key)
    except InvalidSignature:
        logger.error(  # noqa: TRY400 run_periodic already logs the traceback; this adds only the key diagnostic, no stack
            "bundle signature rejected: verifying with pubkey %s, bundle %s signed by key_id=%s for org=%s; "
            "if the pubkey matches the control plane's signing key this is a payload/canonicalization mismatch, not a key mismatch",
            public_key_to_b64(public_key),
            signed.payload.bundle_id,
            signed.signing_key_id,
            signed.payload.org_id,
        )
        raise
    if holder.admit(bundle, bundle_config.staleness_policy, source="polled"):
        write_cached_bundle(bundle_config.cache_dir, signed)


async def run_poller(link: ControlPlaneLink, bundle_config: RemoteBundleConfig, holder: BundleHolder, public_key: Ed25519PublicKey) -> None:
    await run_periodic(
        lambda: poll_once(link, bundle_config, holder, public_key),
        bundle_config.poll_interval_s,
        (httpx.HTTPError, ValidationError, InvalidSignature, OSError),
        "bundle poll",
    )
