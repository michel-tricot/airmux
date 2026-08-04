from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class Config:
    control_plane_url: str | None  # M1 runs from the on-disk bundle alone, polling starts in M3
    dp_token: str | None
    bundle_public_key_b64: str
    cache_dir: Path
    staleness_policy: Literal["serve_and_warn", "refuse"]
    poll_interval_s: float = 30.0
    flush_interval_s: float = 5.0


def load_config() -> Config:
    load_dotenv(find_dotenv(usecwd=True))
    return Config(
        control_plane_url=os.environ.get("GW_CONTROL_PLANE_URL"),
        dp_token=os.environ.get("GW_DP_TOKEN"),
        bundle_public_key_b64=os.environ["GW_BUNDLE_PUBLIC_KEY"],
        cache_dir=Path(os.environ.get("GW_CACHE_DIR", "/var/cache/gateway")),
        staleness_policy="serve_and_warn" if os.environ.get("GW_STALENESS_POLICY", "serve_and_warn") == "serve_and_warn" else "refuse",
    )
