from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gw_contract import BundleV1, KeyEntry


def index_keys(bundle: BundleV1) -> dict[str, KeyEntry]:
    return {k.key_hash: k for k in bundle.keys}


def authenticate(bearer: str, index: dict[str, KeyEntry], revocations: frozenset[str]) -> KeyEntry | None:
    key = index.get(hashlib.sha256(bearer.encode("utf-8")).hexdigest())
    if key is None or key.disabled or key.key_id in revocations:
        return None
    return key
