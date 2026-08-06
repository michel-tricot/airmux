from __future__ import annotations

from typing import TYPE_CHECKING

from contract import INFERENCE_TOKEN_PREFIX, token_hash

if TYPE_CHECKING:
    from contract import BundleV1, KeyEntry


def index_keys(bundle: BundleV1) -> dict[str, KeyEntry]:
    return {k.token_hash: k for k in bundle.keys}


def authenticate(bearer: str, index: dict[str, KeyEntry]) -> KeyEntry | None:
    """Hash the presented bearer and look it up; absence from the bundle is invalidity."""
    if not bearer.startswith(INFERENCE_TOKEN_PREFIX):
        return None
    return index.get(token_hash(bearer))
