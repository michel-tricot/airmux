from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Config:
    control_plane_url: str
    dp_token: str
    bundle_public_key_b64: str
    cache_dir: Path
    staleness_policy: Literal["serve_and_warn", "refuse"]
    poll_interval_s: float = 30.0
    flush_interval_s: float = 5.0


def load_config() -> Config:
    return Config(
        control_plane_url=os.environ["GW_CONTROL_PLANE_URL"],
        dp_token=os.environ["GW_DP_TOKEN"],
        bundle_public_key_b64=os.environ["GW_BUNDLE_PUBLIC_KEY"],
        cache_dir=Path(os.environ.get("GW_CACHE_DIR", "/var/cache/gateway")),
        staleness_policy="serve_and_warn" if os.environ.get("GW_STALENESS_POLICY", "serve_and_warn") == "serve_and_warn" else "refuse",
    )
