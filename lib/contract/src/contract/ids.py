from __future__ import annotations

import os
import time
from uuid import UUID

InferenceKeyId = UUID


def uuid7() -> UUID:
    """RFC 9562 UUIDv7: 48-bit unix milliseconds, then version, then 74 random bits.

    Every server-minted id in either plane comes from here, so ids sort by creation time and
    the timestamp is recoverable. Python 3.13 has no stdlib uuid7; replace with uuid.uuid7 on 3.14.
    """
    timestamp_ms = time.time_ns() // 1_000_000
    rand_a = int.from_bytes(os.urandom(2)) & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8)) & 0x3FFF_FFFF_FFFF_FFFF
    return UUID(int=(timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b)
