from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_token: str
    dp_token: str
    signing_key_b64: str
    signing_key_id: str
    staleness_bound: timedelta


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ["GW_DATABASE_URL"],
        admin_token=os.environ["GW_ADMIN_TOKEN"],
        dp_token=os.environ["GW_DP_TOKEN"],
        signing_key_b64=os.environ["GW_SIGNING_KEY"],
        signing_key_id=os.environ.get("GW_SIGNING_KEY_ID", "k1"),
        staleness_bound=timedelta(hours=float(os.environ.get("GW_STALENESS_BOUND_HOURS", "24"))),
    )
