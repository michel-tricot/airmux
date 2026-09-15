"""Throughput: how many requests per second one data plane sustains, and where it saturates.

Closed-loop load against the gateway, still through the in-process stub upstream so the number
reflects the data plane rather than a real provider's latency. Each concurrency level runs a
fixed wall-clock window with that many worker connections looping as fast as they can; q/s is
completed requests over elapsed time. Sweeping concurrency shows the saturation point, not just
one figure. The absolute number is machine and contention bound (the data plane, the stub and
the load threads share this host), so only a low floor is asserted; read the table for the shape.

    uv run pytest tests/acceptance/full_stack/benchmarks/test_throughput.py -s
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from stack_harness import Bench, Stack

CONCURRENCY = (1, 8, 32, 64)
DURATION_S = 2.0
MIN_PEAK_QPS = 20.0


def _load(url: str, headers: dict[str, str], body: dict, workers: int, duration: float) -> tuple[list[float], float, int]:
    latencies: list[float] = []
    failures: list[int] = []
    lock = threading.Lock()
    deadline = time.monotonic() + duration

    def worker() -> None:
        mine: list[float] = []
        bad = 0
        with httpx.Client(timeout=30.0) as client:
            while time.monotonic() < deadline:
                start = time.perf_counter()
                resp = client.post(url, headers=headers, json=body)
                mine.append((time.perf_counter() - start) * 1000)
                bad += resp.status_code != 200
        with lock:
            latencies.extend(mine)
            if bad:
                failures.append(bad)

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return latencies, time.perf_counter() - started, sum(failures)


def test_single_data_plane_throughput(stack: Stack, bench: Bench) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

    url = f"{stack.dp_url}/inf/v1/chat/completions"
    headers = {"authorization": f"Bearer {stack.caller_api_key}"}
    body = {"model": "echo", "messages": [{"role": "user", "content": "hi"}]}

    _load(url, headers, body, workers=4, duration=0.5)  # warm up connections and the event loop

    rows: list[tuple[object, ...]] = []
    peak = 0.0
    for level in CONCURRENCY:
        latencies, elapsed, failures = _load(url, headers, body, level, DURATION_S)
        assert failures == 0
        qps = len(latencies) / elapsed
        peak = max(peak, qps)
        rows.append(
            (
                level,
                len(latencies),
                f"{qps:.0f}",
                f"{bench.percentile(latencies, 50):.2f}",
                f"{bench.percentile(latencies, 90):.2f}",
                f"{bench.percentile(latencies, 99):.2f}",
            )
        )

    bench.table(
        title="single data plane throughput",
        columns=["concurrency", "requests", "q/s", "p50", "p90", "p99"],
        rows=rows,
        caption=f"closed loop, {DURATION_S:.0f}s per level; latency in ms; peak {peak:.0f} q/s",
    )

    assert peak >= MIN_PEAK_QPS
