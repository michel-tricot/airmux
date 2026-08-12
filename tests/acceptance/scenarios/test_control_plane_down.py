"""Acceptance #2: control plane down. The data plane stays ready, then cold-restarts from the
on-disk bundle and comes back ready with no control plane to poll. This is the test the
architecture exists to pass; serving actual requests through the outage returns with the
request path at rebuild step 3 (notes/design/DATAPLANE.md)."""

from __future__ import annotations

import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conftest import Stack


def test_serves_from_disk_through_outage_and_cold_restart(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_tokens()
    stack.start_dp()
    stack.wait_dp_ready()

    stack.stop("cp")

    assert stack.readyz() == 200

    assert (stack.cache_dir / "bundle.json").exists()
    stack.stop("dp", signal.SIGKILL)
    stack.start_dp()
    stack.wait_dp_ready()
