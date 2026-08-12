"""Performance check: how much latency the data plane adds over a direct upstream call.

Both paths hit the same in-process stub upstream, so the delta isolates the gateway's own
cost: caller-token verification, bundle lookup, request/response transform and usage metering
(including the synchronous event append). Non-streaming, serial, steady-state after warmup.

The `bench` fixture warms up, samples and prints the table. Asserted against a lenient ceiling,
so it catches a gross regression without flaking on a shared CI runner. To see the table on a
passing run:

    uv run pytest tests/acceptance/benchmarks -s
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

pytest.skip("drives /v1/chat/completions; the request path returns at rebuild step 3 (notes/design/DATAPLANE.md)", allow_module_level=True)

if TYPE_CHECKING:
    from conftest import Bench, Stack

MAX_MEDIAN_OVERHEAD_MS = 50.0
MAX_P99_OVERHEAD_MS = 250.0


def test_proxy_overhead_stays_small(stack: Stack, bench: Bench) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_tokens()
    stack.start_dp()
    stack.wait_dp_ready()

    body = {"model": "echo", "messages": [{"role": "user", "content": "hi"}]}
    direct_url = f"http://127.0.0.1:{stack.stub_port}/chat/completions"
    gateway_url = f"{stack.dp_url}/v1/chat/completions"
    auth = {"authorization": f"Bearer {stack.caller_token}"}

    with httpx.Client(timeout=10.0) as direct, httpx.Client(timeout=10.0) as gateway:
        bench.measure("upstream", lambda: direct.post(direct_url, json=body))
        bench.measure("gateway", lambda: gateway.post(gateway_url, headers=auth, json=body))

    bench.report(title="proxy overhead vs direct upstream", baseline="upstream", treatment="gateway")

    assert bench.overhead("gateway", "upstream", 50) < MAX_MEDIAN_OVERHEAD_MS
    assert bench.overhead("gateway", "upstream", 99) < MAX_P99_OVERHEAD_MS
