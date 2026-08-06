"""Acceptance #3: with the control plane down, generate 50 requests. Restart it. All 50 events
land exactly once, verified by distinct event_id count."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conftest import Stack

REQUESTS = 50


def test_buffered_events_replay_exactly_once(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_tokens()
    stack.start_dp()
    stack.wait_dp_ready()

    stack.stop("cp")
    for _ in range(REQUESTS):
        assert stack.request().status_code == 200

    stack.start_cp()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and len(stack.events()) < REQUESTS:
        time.sleep(0.5)

    events = stack.events()
    ids = {e["event_id"] for e in events}
    assert len(ids) == REQUESTS
    assert len(events) == REQUESTS
