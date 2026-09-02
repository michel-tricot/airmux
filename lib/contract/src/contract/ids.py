from __future__ import annotations

import os
import time
from typing import Annotated
from uuid import UUID, uuid5

from pydantic import BeforeValidator

LEGACY_INFERENCE_KEY_NAMESPACE = UUID("9f09b7c3-1424-5c04-a175-eac16b26b2a4")


def inference_key_id(value: object) -> object:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        if not value:
            return value
        try:
            return UUID(value)
        except ValueError:
            return uuid5(LEGACY_INFERENCE_KEY_NAMESPACE, value)
    return value


InferenceKeyId = Annotated[UUID, BeforeValidator(inference_key_id)]


def uuid7() -> UUID:
    """RFC 9562 UUIDv7: 48-bit unix milliseconds, then version, then 74 random bits.

    Every server-minted id in either plane comes from here, so ids sort by creation time and
    the timestamp is recoverable. Python 3.13 has no stdlib uuid7; replace with uuid.uuid7 on 3.14.
    """
    timestamp_ms = time.time_ns() // 1_000_000
    rand_a = int.from_bytes(os.urandom(2)) & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8)) & 0x3FFF_FFFF_FFFF_FFFF
    return UUID(int=(timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b)
