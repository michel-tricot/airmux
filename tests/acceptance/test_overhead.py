"""Performance check: how much latency the data plane adds over a direct upstream call.

Both paths hit the same in-process stub upstream, so the delta isolates the gateway's own
cost: caller-token verification, bundle lookup, request/response transform and usage metering
(including the synchronous event append). Non-streaming, serial, steady-state after warmup.

Reported as percentiles and asserted against a lenient ceiling, so it catches a gross
regression without flaking on a shared CI runner. To see the numbers on a passing run:

    uv run pytest tests/acceptance/test_overhead.py -s
"""

from __future__ import annotations

import statistics
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from conftest import Stack

WARMUP = 20
SAMPLES = 200
MAX_MEDIAN_OVERHEAD_MS = 50.0
MAX_P99_OVERHEAD_MS = 250.0


def _pct(xs: list[float], q: float) -> float:
    ordered = sorted(xs)
    rank = max(0, min(len(ordered) - 1, round(q / 100 * len(ordered)) - 1))
    return ordered[rank]


def _summary(name: str, xs: list[float]) -> str:
    return (
        f"{name:<8} n={len(xs):>4}  p50={_pct(xs, 50):6.2f}  p90={_pct(xs, 90):6.2f}  "
        f"p99={_pct(xs, 99):6.2f}  max={max(xs):6.2f}  mean={statistics.fmean(xs):6.2f}"
    )


def test_proxy_overhead_stays_small(stack: Stack, capsys) -> None:
    stack.write_config()
    stack.start_cp()
    stack.bootstrap()
    stack.start_dp()
    stack.wait_dp_ready()

    body = {"model": "echo", "messages": [{"role": "user", "content": "hi"}]}
    direct_url = f"http://127.0.0.1:{stack.stub_port}/chat/completions"
    gateway_url = f"{stack.dp_url}/v1/chat/completions"
    auth = {"authorization": f"Bearer {stack.caller_token}"}

    def measure(call) -> list[float]:
        out: list[float] = []
        for i in range(WARMUP + SAMPLES):
            start = time.perf_counter()
            resp = call()
            elapsed = (time.perf_counter() - start) * 1000
            assert resp.status_code == 200
            if i >= WARMUP:
                out.append(elapsed)
        return out

    with httpx.Client(timeout=10.0) as direct, httpx.Client(timeout=10.0) as gateway:
        baseline = measure(lambda: direct.post(direct_url, json=body))
        proxied = measure(lambda: gateway.post(gateway_url, headers=auth, json=body))

    overhead_p50 = _pct(proxied, 50) - _pct(baseline, 50)
    overhead_p99 = _pct(proxied, 99) - _pct(baseline, 99)

    report = "\n".join(
        [
            "",
            "proxy overhead (ms), same stub upstream on both paths",
            _summary("upstream", baseline),
            _summary("gateway", proxied),
            f"overhead p50={overhead_p50:6.2f}  p99={overhead_p99:6.2f}",
            "",
        ]
    )
    with capsys.disabled():
        print(report)  # noqa: T201 performance report is for the operator, not a stray debug print

    assert overhead_p50 < MAX_MEDIAN_OVERHEAD_MS
    assert overhead_p99 < MAX_P99_OVERHEAD_MS
