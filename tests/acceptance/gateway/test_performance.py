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
from typer.testing import CliRunner

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
    run_revision(directory, Path(gateway.executable), "candidate", 1, Settings(0.1, 1, 0))
    with sqlite3.connect(directory / "usage/events.db") as events:
        usage = json.loads(events.execute("SELECT body FROM outbox LIMIT 1").fetchone()[0])
    assert (usage["input_tokens"], usage["output_tokens"], usage["cache_read_tokens"]) == (11, 3, 4)
    assert usage["status"] == "ok"


def overhead(revision: Revision, round_number: int, direct_ms: float, proxied_ms: float):
    return performance.OverheadMeasurement(
        direct_before=measurement(revision, round_number, direct_ms, direct_ms / 2, 100),
        proxied=measurement(revision, round_number, proxied_ms, proxied_ms / 2, 80),
        direct_after=measurement(revision, round_number, direct_ms, direct_ms / 2, 100),
    )


def test_overhead_uses_mean_difference_and_retains_matched_throughput():
    timings = overhead("base", 1, 10, 15)
    timings.proxied.latency_ms = [10] * 9 + [60]
    metrics = timings.metrics()
    assert metrics["overhead_mean_ms"] == 5
    assert metrics["first_content_overhead_mean_ms"] == 2.5
    assert metrics["direct_requests_per_second"] == 100
    assert metrics["proxied_requests_per_second"] == 80
    assert metrics["throughput_cost_pct"] == pytest.approx(20)


@pytest.mark.parametrize("field", ["revision", "round", "scenario", "concurrency"])
def test_overhead_rejects_unmatched_controls(field: str):
    timings = overhead("base", 1, 10, 15).model_dump()
    timings["direct_after"][field] = {"revision": "candidate", "round": 2, "scenario": "buffered", "concurrency": 8}[field]
    with pytest.raises(ValidationError, match="matched"):
        performance.OverheadMeasurement.model_validate(timings)


@pytest.mark.parametrize("direct_ms", [float("nan"), float("inf"), 0, -1])
def test_overhead_rejects_invalid_timings(direct_ms: float):
    with pytest.raises(ValidationError):
        overhead("base", 1, direct_ms, 15)


def test_overhead_comparison_rejects_unpaired_and_duplicate_rounds():
    with pytest.raises(ValueError, match="paired"):
        performance.overhead_comparisons([])
    with pytest.raises(ValueError, match="paired"):
        performance.overhead_comparisons([overhead("base", 1, 10, 15), overhead("candidate", 2, 10, 16)])
    with pytest.raises(ValueError, match="duplicate"):
        performance.overhead_comparisons([overhead("base", 1, 10, 15)] * 2)


@pytest.mark.parametrize(
    ("base_ms", "candidate_ms", "regression"),
    [(2, 4, True), (0.5, 0.8, False), (-1, 2, False), (0, 2, False), (2, -1, False), (5, 6, False), (5, 6.01, True)],
)
def test_overhead_regression_preserves_nonpositive_estimates(base_ms: float, candidate_ms: float, regression: bool):
    changes = performance.overhead_comparisons(
        [
            overhead(revision, round_number, 10, 10 + cost)
            for round_number in range(1, 6)
            for revision, cost in (("base", base_ms), ("candidate", candidate_ms))
        ]
    )
    latency = next(change for change in changes if change.metric == "overhead_mean_ms")
    assert latency.base == base_ms
    assert latency.candidate == pytest.approx(candidate_ms)
    assert latency.absolute_change == pytest.approx(candidate_ms - base_ms)
    assert latency.regression is regression
    assert (latency.change_pct is None) == (min(base_ms, candidate_ms) <= 0)
    assert latency.noisy == (min(base_ms, candidate_ms) <= 0)


def test_overhead_reports_control_drift_and_round_noise():
    timings = [overhead(revision, round_number, 10, 11) for round_number in range(1, 6) for revision in ("base", "candidate")]
    timings[0].direct_after.latency_ms = [14] * 10
    changes = performance.overhead_comparisons(timings)
    latency = next(change for change in changes if change.metric == "overhead_mean_ms")
    assert latency.base == 1
    assert latency.base_range == (-1, 1)
    assert latency.max_control_drift == 4
    assert latency.noisy


def test_provider_wait_is_not_attributed_to_gateway_overhead(gateway: Gateway, tmp_path: Path):
    results = {
        delay: run_revision(tmp_path / f"delay-{delay}", Path(gateway.executable), "candidate", 1, Settings(0.3, 3, delay)) for delay in (0, 50)
    }
    for scenario in ("buffered", "stream", "policies"):
        workloads = {
            delay: next(timings for timings in result.overhead if timings.proxied.scenario == scenario and timings.proxied.concurrency == 1)
            for delay, result in results.items()
        }
        metric = "first_content_overhead_mean_ms" if scenario == "stream" else "overhead_mean_ms"
        assert workloads[50].direct_before.metrics()["p50_ms"] - workloads[0].direct_before.metrics()["p50_ms"] > 40
        assert abs(workloads[50].metrics()[metric] - workloads[0].metrics()[metric]) < 15


def test_overhead_summary_and_raw_data_reproduce_comparisons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def run(directory: Path, executable: Path, revision: Revision, round_number: int, settings: Settings):
        timings = overhead(revision, round_number, 10, 12 if revision == "base" else 14)
        return performance.RevisionMeasurements(measurements=[timings.proxied], overhead=[timings], metering_events=11)

    monkeypatch.setattr(performance, "run_revision", run)
    executable = tmp_path / "airmux"
    executable.touch()
    output = tmp_path / "report"
    result = CliRunner().invoke(
        performance.app,
        [
            "--base-bin",
            str(executable),
            "--candidate-bin",
            str(executable),
            "--base-revision",
            "base-sha",
            "--candidate-revision",
            "candidate-sha",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads((output / "measurements.json").read_text())
    timings = [
        performance.OverheadMeasurement.model_validate({key: value for key, value in sample.items() if key != "derived"})
        for sample in report["overhead_measurements"]
    ]
    assert [change.model_dump(mode="json") for change in performance.overhead_comparisons(timings)] == report["overhead_comparisons"]
    assert [sample.metrics() for sample in timings] == [sample["derived"] for sample in report["overhead_measurements"]]
    assert [sample.proxied.revision for sample in timings] == [
        "base",
        "candidate",
        "candidate",
        "base",
        "base",
        "candidate",
        "candidate",
        "base",
        "base",
        "candidate",
    ]
    assert (report["base_revision"], report["candidate_revision"]) == ("base-sha", "candidate-sha")
    assert len(report["metering_event_counts"]) == 10
    summary = (output / "summary.md").read_text()
    assert "Incremental gateway overhead" in summary
    assert "Durable SQLite" in summary
    assert "Absolute change" in summary
    assert "Potential regression" in summary
    assert "::warning::" in result.output
