from __future__ import annotations

import asyncio
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from smoke import run

PROVIDER = {
    "id": "example",
    "base_url": "https://example.test/v1",
    "ingress": ["oai"],
    "surfaces": {
        "oai": {
            "endpoint": "chat/completions",
            "auth": "bearer",
            "egress_kind": "openai_compatible",
            "headers": {},
        }
    },
}


def test_reachability_retries_transient_failures(monkeypatch):
    outcomes = iter([("rate_limit", "slow down"), ("ok", "ok")])
    calls = []

    async def no_sleep(delay):
        return None

    monkeypatch.setattr("smoke.request", lambda *args: calls.append(args) or next(outcomes))
    monkeypatch.setattr("smoke.asyncio.sleep", no_sleep)

    results = asyncio.run(run([(PROVIDER, "new-model", "chat/completions", "new-model", "key")]))

    assert len(calls) == 2
    assert results[0].outcome == "ok"
