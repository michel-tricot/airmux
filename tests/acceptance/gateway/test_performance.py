from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import performance
import pytest
from performance import Measurement, Revision, Settings, comparisons, request, run_revision
from pydantic import ValidationError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from gateway_harness import Gateway


def measurement(revision: Revision, round_number: int, total_ms: float, first_content_ms: float, qps: float) -> Measurement:
    return Measurement(
        revision=revision,
        round=round_number,
        scenario="stream",
        concurrency=1,
        elapsed_s=10 / qps,
        latency_ms=[total_ms] * 10,
        first_content_ms=[first_content_ms] * 10,
    )


def test_regression_report_compares_repeated_rounds_without_following_one_outlier():
    measurements = [
        measurement(revision, round_number, latency, first_content, qps)
        for round_number in range(1, 6)
        for revision, latency, first_content, qps in (
            ("base", 10, 5, 100),
            ("candidate", 100 if round_number == 1 else 10, 50 if round_number == 1 else 5, 10 if round_number == 1 else 100),
        )
    ]
    changes = comparisons(measurements)
    assert all(change.change_pct == 0 and not change.regression for change in changes)


def test_regression_report_detects_slower_streaming_and_lower_throughput():
    measurements = [
        measurement(revision, round_number, latency, first_content, qps)
        for round_number in range(1, 4)
        for revision, latency, first_content, qps in (("base", 10, 5, 100), ("candidate", 15, 8, 60))
    ]
    changes = {change.metric: change for change in comparisons(measurements)}
    assert changes["p50_ms"].change_pct == pytest.approx(50)
    assert changes["first_content_p50_ms"].change_pct == pytest.approx(60)
    assert changes["requests_per_second"].change_pct == pytest.approx(-40)
    assert all(change.regression for change in changes.values())


def test_regression_report_does_not_flag_small_absolute_latency_changes():
    measurements = [
        measurement(revision, round_number, latency, first_content, qps)
        for round_number in range(1, 4)
        for revision, latency, first_content, qps in (("base", 0.5, 0.5, 100), ("candidate", 0.8, 0.8, 100))
    ]
    assert not any(change.regression for change in comparisons(measurements))


def test_regression_report_rejects_unpaired_rounds():
    with pytest.raises(ValueError, match="paired"):
        comparisons([measurement("base", 1, 10, 5, 100), measurement("candidate", 2, 15, 8, 60)])


def test_regression_report_rejects_duplicate_rounds():
    with pytest.raises(ValueError, match="duplicate"):
        comparisons([measurement("base", 1, 10, 5, 100), measurement("base", 1, 100, 50, 10), measurement("candidate", 1, 15, 8, 60)])


@pytest.mark.parametrize("first_content_ms", [[1], [1, 1, 1], [20, 20]], ids=["missing_sample", "extra_sample", "after_completion"])
def test_performance_timings_reject_inconsistent_samples(first_content_ms: list[float]):
    with pytest.raises(ValidationError, match="content timings"):
        Measurement(revision="base", round=1, scenario="stream", concurrency=1, elapsed_s=1, latency_ms=[10, 10], first_content_ms=first_content_ms)


async def test_stream_timing_measures_text_after_metadata_and_rejects_missing_terminal(monkeypatch: pytest.MonkeyPatch):
    clock = [10.0]
    monkeypatch.setattr(performance.time, "perf_counter", lambda: clock[0])

    class TimedStream(httpx.AsyncByteStream):
        def __init__(self, terminal: bool) -> None:
            self.terminal = terminal

        async def __aiter__(self) -> AsyncIterator[bytes]:
            clock[0] = 10.001
            yield b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
            clock[0] = 10.025
            yield ("data: " + json.dumps({"choices": [{"delta": {"content": "hello 🌍"}}]}) + "\n\n").encode()
            clock[0] = 10.080
            if self.terminal:
                yield b"data: [DONE]\n\n"

    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=TimedStream(terminal=request.url.path == "/complete"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        sample = await request(client, "http://upstream/complete", {}, {"stream": True})
        assert sample.first_content_ms == pytest.approx(25)
        assert sample.latency_ms == pytest.approx(80)
        clock[0] = 10.0
        with pytest.raises(AssertionError, match="terminal"):
            await request(client, "http://upstream/incomplete", {}, {"stream": True})


def test_performance_load_preserves_usage_with_integration_artifacts_enabled(gateway: Gateway, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AIRMUX_GATEWAY_ARTIFACTS", str(tmp_path / "artifacts"))
    directory = tmp_path / "performance"
    run_revision(directory, Path(gateway.executable), "candidate", 1, Settings(0.1, 1))
    with sqlite3.connect(directory / "usage/events.db") as events:
        usage = json.loads(events.execute("SELECT body FROM outbox LIMIT 1").fetchone()[0])
    assert (usage["input_tokens"], usage["output_tokens"], usage["cache_read_tokens"]) == (11, 3, 4)
    assert usage["status"] == "ok"
