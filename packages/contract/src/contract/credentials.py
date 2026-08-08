"""The cross-plane credential agreement: prefix and hash format.

The control plane writes token_hash(plaintext) into the bundle key index and the data
plane hashes the presented bearer to look it up, so both planes must agree byte for
byte. Minting stays in the control plane; nothing here touches secrets at rest.
Lookup through a unique index on the hash is the timing-safe comparison.
"""

from __future__ import annotations

import hashlib

INFERENCE_TOKEN_PREFIX = "sk-inf-"  # noqa: S105 token prefix, not a secret


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
