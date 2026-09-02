"""Acceptance: bundle distribution and event delivery without inference traffic.

Before it can serve inference, a data plane must prove bundle distribution down (poll, verify,
admit) and event tracking up (buffer, flush, ingest exactly once).
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
from conftest import ADMIN_EMAIL, ADMIN_PASSWORD

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import Stack


def _wait(predicate: Callable[[], bool], timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.5)
    return False


def _synthetic_event(org_id: str, event_id: str) -> str:
    """A UsageEventV1 as plain JSON; the harness speaks wire shapes, never the contract package."""
    return json.dumps(
        {
            "schema_version": 1,
            "event_id": event_id,
            "request_id": str(uuid4()),
            "occurred_at": datetime.now(tz=UTC).isoformat(),
            "org_id": org_id,
            "workspace_id": str(uuid4()),
            "key_id": "k-synthetic",
            "model_id": "echo",
            "provider_id": "stub",
            "bundle_id": str(uuid4()),
            "input_tokens": 11,
            "output_tokens": 3,
            "cost_usd": 0.0,
            "latency_ms": 0,
            "status": "ok",
            "stream": False,
            "credential_id": str(uuid4()),
            "credential_scope": "workspace",
        }
    )


def _buffer_event(stack: Stack, event_id: str, body: str) -> None:
    """Record into the shared outbox from a second process, the way another worker would."""
    with sqlite3.connect(str(stack.cache_dir / "events.db"), timeout=5.0) as conn:
        conn.execute("INSERT OR IGNORE INTO outbox(event_id, body) VALUES (?, ?)", (event_id, body))


def test_skeleton_syncs_bundle_heartbeat_and_events(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()  # readyz turns 200 only once a signed bundle is verified and admitted

    with httpx.Client(base_url=stack.cp_url, headers={"X-Requested-With": "XMLHttpRequest"}, timeout=10.0) as admin:
        login = admin.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        login.raise_for_status()
        org_id = login.json()["data"]["orgs"][0]

        def data_planes_online() -> bool:
            resp = admin.get("/api/v1/instance/data-planes")
            resp.raise_for_status()
            return len(resp.json()["data"]) >= 1

        assert _wait(data_planes_online), "no heartbeat reached the instance roster"

    event_id = str(uuid4())
    body = _synthetic_event(org_id, event_id)
    _buffer_event(stack, event_id, body)
    assert _wait(lambda: any(e["event_id"] == event_id for e in stack.events())), "the buffered event never reached the control plane"

    _buffer_event(stack, event_id, body)  # a replay: the outbox already flushed and forgot this event once
    time.sleep(3)  # several flush intervals, so the replay has certainly shipped
    assert [e["event_id"] for e in stack.events()].count(event_id) == 1, "a replayed event_id must land exactly once"
