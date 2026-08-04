from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_token: str
    dp_token: str
    signing_key_b64: str
    signing_key_id: str
    staleness_bound: timedelta
    dev: bool = False  # set by the --dev flag on the entry point, gate dev-only behavior on this


def load_settings() -> Settings:
    load_dotenv(find_dotenv(usecwd=True))
    return Settings(
        database_url=os.environ.get("GW_DATABASE_URL", "sqlite+aiosqlite:///airllm.db"),
        admin_token=os.environ["GW_ADMIN_TOKEN"],
        dp_token=os.environ["GW_DP_TOKEN"],
        signing_key_b64=os.environ["GW_SIGNING_KEY"],
        signing_key_id=os.environ.get("GW_SIGNING_KEY_ID", "k1"),
        staleness_bound=timedelta(hours=float(os.environ.get("GW_STALENESS_BOUND_HOURS", "24"))),
        dev=os.environ.get("GW_DEV") == "1",
    )
