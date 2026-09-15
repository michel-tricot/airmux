"""Acceptance #2: control plane down. The data plane serves 100 requests, then cold-restarts
from the on-disk bundle and keeps serving. This is the test the architecture exists to pass."""

from __future__ import annotations

import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stack_harness import Stack


def test_serves_from_disk_through_outage_and_cold_restart(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()
    assert stack.request().status_code == 200

    stack.stop("cp")

    for _ in range(100):
        assert stack.request().status_code == 200

    assert (stack.cache_dir / "bundles.json").exists()
    stack.stop("dp", signal.SIGKILL)
    stack.start_dp()
    stack.wait_dp_ready()

    assert stack.request().status_code == 200
