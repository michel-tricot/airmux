from __future__ import annotations

import asyncio
import json
import math
import os
import platform
import socket
import sqlite3
import statistics
import subprocess
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, NamedTuple

import httpx
import typer
import yaml
from gateway_harness import Gateway, eventually
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, model_validator
from upstream import TEXT, UPSTREAM_KEY

if TYPE_CHECKING:
    from typing import Self

Revision = Literal["base", "candidate"]
Scenario = Literal["upstream", "buffered", "stream", "policies"]
Metric = Literal["p50_ms", "p95_ms", "p99_ms", "first_content_p50_ms", "requests_per_second"]
WORKLOADS: tuple[tuple[Scenario, int], ...] = (
    ("upstream", 1),
    ("upstream", 32),
    ("buffered", 1),
    ("stream", 1),
    ("buffered", 8),
    ("buffered", 32),
    ("policies", 1),
)
LATENCY_METRICS: tuple[Metric, ...] = ("p50_ms", "p95_ms", "p99_ms", "first_content_p50_ms")
REGRESSION_PCT = 20
MIN_LATENCY_CHANGE_MS = 1
POLICY_COUNT = 100
app = typer.Typer()


class Settings(NamedTuple):
    duration_s: float
    warmup: int
    upstream_delay_ms: float


class PerformanceGateway(Gateway):
    def write_files(self) -> None:
        super().write_files()
        configuration = yaml.safe_load(self.config_path.read_text())
        configuration["data_plane"]["events"] = {
            "kind": "sqlite",
            "cache_dir": "usage",
            "flush_interval_s": 3600,
            "control_plane": {"url": "http://127.0.0.1:1", "token": "benchmark-export-token"},
        }
        self.config_path.write_text(yaml.safe_dump(configuration), encoding="utf-8")

    def close(self) -> None:
        self.stop()
        self.log.close()


def percentile(values: list[float], quantile: float) -> float:
    return sorted(values)[math.ceil(len(values) * quantile) - 1]


class Measurement(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    revision: Revision
    round: PositiveInt
    scenario: Scenario
    concurrency: PositiveInt
    elapsed_s: PositiveFloat
    latency_ms: list[PositiveFloat] = Field(min_length=1)
    first_content_ms: list[PositiveFloat] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_timings(self) -> Self:
        if len(self.latency_ms) != len(self.first_content_ms) or any(
            first_content > latency for first_content, latency in zip(self.first_content_ms, self.latency_ms, strict=True)
        ):
            message = "First content timings must pair with request latencies and precede completion"
            raise ValueError(message)
        return self

    def metrics(self) -> dict[Metric, float]:
        return {
            "p50_ms": percentile(self.latency_ms, 0.5),
            "p95_ms": percentile(self.latency_ms, 0.95),
            "p99_ms": percentile(self.latency_ms, 0.99),
            "first_content_p50_ms": percentile(self.first_content_ms, 0.5),
            "requests_per_second": len(self.latency_ms) / self.elapsed_s,
        }


class Comparison(BaseModel):
    scenario: Scenario
    concurrency: PositiveInt
    metric: Metric
    base: PositiveFloat
    candidate: PositiveFloat
    change_pct: float
    regression: bool


def comparisons(measurements: list[Measurement]) -> list[Comparison]:
    identities = [(measurement.revision, measurement.round, measurement.scenario, measurement.concurrency) for measurement in measurements]
    if len(identities) != len(set(identities)):
        message = "Performance comparisons cannot contain duplicate rounds"
        raise ValueError(message)
    changes: list[Comparison] = []
    for scenario, concurrency in dict.fromkeys((measurement.scenario, measurement.concurrency) for measurement in measurements):
        paired = {
            revision: {
                measurement.round: measurement.metrics()
                for measurement in measurements
                if (measurement.revision, measurement.scenario, measurement.concurrency) == (revision, scenario, concurrency)
            }
            for revision in ("base", "candidate")
        }
        if not paired["base"] or paired["base"].keys() != paired["candidate"].keys():
            message = "Performance comparisons require paired base and candidate rounds"
            raise ValueError(message)
        for metric in (*LATENCY_METRICS, "requests_per_second"):
            if metric == "first_content_p50_ms" and scenario != "stream":
                continue
            base = statistics.median(metrics[metric] for metrics in paired["base"].values())
            candidate = statistics.median(metrics[metric] for metrics in paired["candidate"].values())
            change_pct = (candidate / base - 1) * 100
            regression = (
                candidate < base * (1 - REGRESSION_PCT / 100)
                if metric == "requests_per_second"
                else candidate > base * (1 + REGRESSION_PCT / 100) and candidate - base > MIN_LATENCY_CHANGE_MS
            )
            changes.append(
                Comparison(
                    scenario=scenario,
                    concurrency=concurrency,
                    metric=metric,
                    base=base,
                    candidate=candidate,
                    change_pct=change_pct,
                    regression=regression,
                )
            )
    return changes


OverheadMetric = Literal[
    "overhead_mean_ms", "first_content_overhead_mean_ms", "direct_requests_per_second", "proxied_requests_per_second", "throughput_cost_pct"
]
OVERHEAD_METHOD = (
    "Incremental HTTP proxy cost, not gateway code execution time. For each workload/round, subtract the equally weighted "
    "means of warmed direct-before and direct-after windows from the proxied window mean. Streaming uses first non-empty content. "
    "Report the median of these signed round estimates; no subtraction of p95/p99 and no per-request overhead percentile. "
    "Throughput cost = 100 * (1 - proxied RPS / mean(direct-before RPS, direct-after RPS)). "
    "Durable SQLite event collection is enabled and included; authentication, translation, policy and metering stay active. "
    "Model inference, external network/provider variability, control-plane traffic, periodic polling/export, startup and warmup are excluded. "
    "Controls match request fields (using the upstream model name), response fixture, streaming, concurrency and HTTP/1.1 keepalive limits. "
    "One sequential closed-loop request per connection; windows run separately without competing direct/proxied load. "
    "Client parsing, the extra local HTTP hop, scheduling, queueing and connection-pool effects are included. "
    "Round ranges and maximum direct-control drift show noise, not confidence intervals; non-positive estimates are retained. "
    "Shared-runner measurements do not isolate CPU execution or establish statistical significance."
)


class OverheadMeasurement(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    direct_before: Measurement
    proxied: Measurement
    direct_after: Measurement

    @model_validator(mode="after")
    def matched_controls(self) -> Self:
        identities = {
            (measurement.revision, measurement.round, measurement.scenario, measurement.concurrency)
            for measurement in (self.direct_before, self.proxied, self.direct_after)
        }
        if len(identities) != 1 or self.proxied.scenario == "upstream":
            message = "Overhead requires matched direct controls and a proxied workload"
            raise ValueError(message)
        return self

    def metrics(self) -> dict[OverheadMetric, float]:
        direct_rps = statistics.mean(control.metrics()["requests_per_second"] for control in (self.direct_before, self.direct_after))
        proxied_rps = self.proxied.metrics()["requests_per_second"]
        return {
            "overhead_mean_ms": self.difference("latency_ms"),
            "first_content_overhead_mean_ms": self.difference("first_content_ms"),
            "direct_requests_per_second": direct_rps,
            "proxied_requests_per_second": proxied_rps,
            "throughput_cost_pct": 100 * (1 - proxied_rps / direct_rps),
        }

    def difference(self, timing: Literal["latency_ms", "first_content_ms"]) -> float:
        return statistics.mean(getattr(self.proxied, timing)) - statistics.mean(
            statistics.mean(getattr(control, timing)) for control in (self.direct_before, self.direct_after)
        )

    def control_drift(self, metric: OverheadMetric) -> float:
        timing = "first_content_ms" if metric == "first_content_overhead_mean_ms" else "latency_ms"
        return abs(statistics.mean(getattr(self.direct_before, timing)) - statistics.mean(getattr(self.direct_after, timing)))


class OverheadComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    scenario: Scenario
    concurrency: PositiveInt
    metric: OverheadMetric
    base: float
    candidate: float
    absolute_change: float
    change_pct: float | None
    base_range: tuple[float, float]
    candidate_range: tuple[float, float]
    max_control_drift: float | None
    noisy: bool
    regression: bool


def overhead_comparisons(measurements: list[OverheadMeasurement]) -> list[OverheadComparison]:
    if not measurements:
        message = "Overhead comparisons require paired base and candidate rounds"
        raise ValueError(message)
    comparisons([measurement.proxied for measurement in measurements])
    changes: list[OverheadComparison] = []
    for scenario, concurrency in dict.fromkeys((measurement.proxied.scenario, measurement.proxied.concurrency) for measurement in measurements):
        paired = {
            revision: [
                measurement
                for measurement in measurements
                if (measurement.proxied.revision, measurement.proxied.scenario, measurement.proxied.concurrency) == (revision, scenario, concurrency)
            ]
            for revision in ("base", "candidate")
        }
        for metric in paired["base"][0].metrics():
            if metric == "first_content_overhead_mean_ms" and scenario != "stream":
                continue
            values = {revision: [measurement.metrics()[metric] for measurement in rounds] for revision, rounds in paired.items()}
            base, candidate = (statistics.median(values[revision]) for revision in ("base", "candidate"))
            latency = metric in ("overhead_mean_ms", "first_content_overhead_mean_ms")
            drift = max(measurement.control_drift(metric) for rounds in paired.values() for measurement in rounds) if latency else None
            noisy = latency and (min(*values["base"], *values["candidate"]) <= 0 or (drift is not None and drift >= min(base, candidate)))
            changes.append(
                OverheadComparison(
                    scenario=scenario,
                    concurrency=concurrency,
                    metric=metric,
                    base=base,
                    candidate=candidate,
                    absolute_change=candidate - base,
                    change_pct=(candidate / base - 1) * 100 if base > 0 and candidate > 0 else None,
                    base_range=(min(values["base"]), max(values["base"])),
                    candidate_range=(min(values["candidate"]), max(values["candidate"])),
                    max_control_drift=drift,
                    noisy=noisy,
                    regression=(
                        base > 0 and candidate > base * (1 + REGRESSION_PCT / 100) and candidate - base > MIN_LATENCY_CHANGE_MS
                        if latency
                        else metric == "proxied_requests_per_second" and candidate < base * (1 - REGRESSION_PCT / 100)
                    ),
                )
            )
    return changes


class RevisionMeasurements(BaseModel):
    measurements: list[Measurement]
    overhead: list[OverheadMeasurement]
    metering_events: PositiveInt


class FastProvider:
    def __init__(self, directory: Path, delay_ms: float) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.delay_ms = delay_ms
        self.url = f"http://127.0.0.1:{self.port}"
        self.log = (directory / "upstream.log").open("a", encoding="utf-8")
        self.process: subprocess.Popen[bytes] | None = None

    def start(self) -> None:
        self.process = subprocess.Popen(  # noqa: S603 the benchmark starts its trusted local upstream script
            [sys.executable, str(Path(__file__).with_name("performance_upstream.py")), "--port", str(self.port), "--delay-ms", str(self.delay_ms)],
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )

        def ready() -> bool:
            assert self.process is not None
            assert self.process.poll() is None, "benchmark upstream exited before readiness"
            return httpx.get(self.url + "/readyz", timeout=1).status_code == 200

        eventually(ready)

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.log.close()


class Sample(NamedTuple):
    latency_ms: float
    first_content_ms: float


async def request(client: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, object]) -> Sample:
    started = time.perf_counter()
    first_content = 0.0
    async with client.stream("POST", url, headers=headers, json=body) as response:
        response.raise_for_status()
        if body.get("stream"):
            texts: list[str] = []
            terminal = False
            async for line in response.aiter_lines():
                if line == "data: [DONE]":
                    terminal = True
                elif line.startswith("data: "):
                    event = json.loads(line[6:])
                    for choice in event.get("choices", []):
                        text = choice.get("delta", {}).get("content")
                        if text:
                            if not texts:
                                first_content = time.perf_counter()
                            texts.append(text)
            assert "".join(texts) == TEXT, "benchmark stream did not return the expected text"
            assert terminal, "benchmark stream did not return the expected terminal"
        else:
            response_body = json.loads(await response.aread())
            first_content = time.perf_counter()
            assert response_body["choices"][0]["message"]["content"] == TEXT, "benchmark response did not return the expected text"
    finished = time.perf_counter()
    return Sample((finished - started) * 1000, (first_content - started) * 1000)


async def measure(url: str, headers: dict[str, str], body: dict[str, object], concurrency: int, settings: Settings) -> tuple[list[Sample], float]:
    async with AsyncExitStack() as connections:
        clients = [
            await connections.enter_async_context(
                httpx.AsyncClient(timeout=10, trust_env=False, limits=httpx.Limits(max_connections=1, max_keepalive_connections=1))
            )
            for _ in range(concurrency)
        ]

        async def warm(client: httpx.AsyncClient) -> None:
            for _ in range(settings.warmup):
                await request(client, url, headers, body)

        await asyncio.gather(*(warm(client) for client in clients))
        started = time.perf_counter()
        deadline = started + settings.duration_s

        async def worker(client: httpx.AsyncClient) -> list[Sample]:
            samples: list[Sample] = []
            while time.perf_counter() < deadline:
                samples.append(await request(client, url, headers, body))
            return samples

        workers = await asyncio.gather(*(worker(client) for client in clients))
        return [sample for samples in workers for sample in samples], time.perf_counter() - started


def request_body(scenario: Scenario, *, direct: bool) -> dict[str, object]:
    return {
        "model": "upstream-model-a" if direct else "model-a",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 50,
        **({"stream": True, "stream_options": {"include_usage": True}} if scenario == "stream" else {}),
    }


def run_revision(directory: Path, executable: Path, revision: Revision, round_number: int, settings: Settings) -> RevisionMeasurements:
    gateway = PerformanceGateway(directory, f"performance-{revision}-{round_number}")
    provider = FastProvider(directory, settings.upstream_delay_ms)
    gateway.executable = str(executable.resolve())
    gateway.reload_interval_s = 3600
    gateway.taxonomy = {
        "providers": [{"provider_id": "stub", "kind": "openai_compatible", "base_url": provider.url}],
        "models": [
            {
                "model_id": "model-a",
                "provider_id": "stub",
                "upstream_model": "upstream-model-a",
                "input_price_per_mtok": 2,
                "output_price_per_mtok": 5,
                "context_window": 128000,
                "max_output_tokens": 4096,
                "input_modalities": ["text"],
                "output_modalities": ["text"],
                "capabilities": ["streaming"],
            }
        ],
    }
    measurements: list[Measurement] = []
    overhead_measurements: list[OverheadMeasurement] = []
    event_count = 0
    try:
        provider.start()
        gateway.start()
        for scenario, concurrency in WORKLOADS:
            if scenario == "policies":
                gateway.stop()
                for priority in range(POLICY_COUNT):
                    gateway.add_policy([{"kind": "request_limits", "max_output_tokens": 100}], priority=priority)
                gateway.start()
            direct = scenario == "upstream"
            body = request_body(scenario, direct=direct)

            def window(proxied: bool, scenario: Scenario, concurrency: int, body: dict[str, object]) -> Measurement:
                url = gateway.url + "/inf/v1/chat/completions" if proxied else provider.url + "/chat/completions"
                samples, elapsed_s = asyncio.run(
                    measure(
                        url,
                        gateway.headers("openai_native") if proxied else {"Authorization": f"Bearer {UPSTREAM_KEY}"},
                        body if proxied else {**body, "model": "upstream-model-a"},
                        concurrency,
                        settings,
                    )
                )
                return Measurement(
                    revision=revision,
                    round=round_number,
                    scenario=scenario,
                    concurrency=concurrency,
                    elapsed_s=elapsed_s,
                    latency_ms=[sample.latency_ms for sample in samples],
                    first_content_ms=[sample.first_content_ms for sample in samples],
                )

            before = window(False, scenario, concurrency, body)
            if direct:
                measurements.append(before)
                continue
            proxied = window(True, scenario, concurrency, body)
            after = window(False, scenario, concurrency, body)
            event_count += settings.warmup * concurrency + len(proxied.latency_ms)
            measurements.append(proxied)
            overhead_measurements.append(OverheadMeasurement(direct_before=before, proxied=proxied, direct_after=after))
        with sqlite3.connect(directory / "usage/events.db") as events:
            eventually(lambda: events.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == event_count)
            assert events.execute("SELECT COUNT(*) FROM outbox WHERE json_extract(body, '$.status') != 'ok'").fetchone()[0] == 0
    finally:
        try:
            gateway.close()
        finally:
            provider.close()
    return RevisionMeasurements(measurements=measurements, overhead=overhead_measurements, metering_events=event_count)


@app.command()
def benchmark(  # noqa: PLR0913 flags define the benchmark command interface
    *,
    base_bin: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    candidate_bin: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option()],
    base_revision: Annotated[str, typer.Option()],
    candidate_revision: Annotated[str, typer.Option()],
    rounds: Annotated[int, typer.Option(min=3)] = 5,
    duration_s: Annotated[float, typer.Option(min=0.1)] = 2,
    warmup: Annotated[int, typer.Option(min=1)] = 20,
    upstream_delay_ms: Annotated[float, typer.Option(min=0, max=1000)] = 0,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    measurements: list[Measurement] = []
    overhead_measurements: list[OverheadMeasurement] = []
    event_counts: list[dict[str, str | int]] = []
    for round_number in range(1, rounds + 1):
        directory = output / f"round-{round_number}"
        directory.mkdir()
        order: tuple[Revision, ...] = ("base", "candidate") if round_number % 2 else ("candidate", "base")
        for revision in order:
            typer.echo(f"Round {round_number}/{rounds}: {revision}")
            result = run_revision(
                directory / revision,
                base_bin if revision == "base" else candidate_bin,
                revision,
                round_number,
                Settings(duration_s, warmup, upstream_delay_ms),
            )
            measurements.extend(result.measurements)
            overhead_measurements.extend(result.overhead)
            event_counts.append({"revision": revision, "round": round_number, "verified_metering_events": result.metering_events})
    changes = comparisons(measurements)
    overhead_changes = overhead_comparisons(overhead_measurements)
    report = {
        "schema_version": 2,
        "overhead_methodology": OVERHEAD_METHOD,
        "overhead_measurements": [{**measurement.model_dump(), "derived": measurement.metrics()} for measurement in overhead_measurements],
        "overhead_comparisons": [change.model_dump() for change in overhead_changes],
        "metering_event_counts": event_counts,
        "upstream_delay_ms": upstream_delay_ms,
        "connection_settings": {"http_version": "1.1", "max_connections_per_client": 1, "keepalive_connections_per_client": 1, "timeout_s": 10},
        "gateway_settings": {"workers": 1, "event_store": "sqlite", "reload_interval_s": 3600, "export_interval_s": 3600},
        "runner": {name: os.environ.get(name) for name in ("RUNNER_OS", "RUNNER_ARCH", "RUNNER_NAME", "ImageOS", "ImageVersion")},
        "base_revision": base_revision,
        "candidate_revision": candidate_revision,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "rounds": rounds,
        "duration_s": duration_s,
        "warmup_per_connection": warmup,
        "policy_count": POLICY_COUNT,
        "workloads": [
            {
                "scenario": scenario,
                "concurrency": concurrency,
                "direct_request": request_body(scenario, direct=True),
                "proxied_request": request_body(scenario, direct=False),
            }
            for scenario, concurrency in WORKLOADS
        ],
        "measurements": [measurement.model_dump() for measurement in measurements],
        "comparisons": [change.model_dump() for change in changes],
    }
    (output / "measurements.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    sections = [
        "## Gateway performance",
        "",
        f"Base `{base_revision}` vs candidate `{candidate_revision}` on the same runner, alternating execution order.",
        "",
        (
            f"Medians across {rounds} rounds, {duration_s:g}s per workload, {warmup} warmup requests per connection. "
            "One gateway worker, durable SQLite event collection enabled; periodic export excluded."
        ),
        "",
        "| Workload | Concurrency | Metric | Base | Candidate | Change |",
        "| --- | ---: | --- | ---: | ---: | ---: |",
    ]
    for change in changes:
        flag = " Potential regression" if change.regression else ""
        sections.append(
            f"| {change.scenario} | {change.concurrency} | {change.metric} | "
            f"{change.base:.2f} | {change.candidate:.2f} | {change.change_pct:+.1f}%{flag} |"
        )
    sections.extend(
        [
            "",
            "### Incremental gateway overhead",
            "",
            OVERHEAD_METHOD,
            "",
            "| Workload | Concurrency | Metric | Base | Candidate | Absolute change | Change | Base range | Candidate range | Control drift (ms) |",
            "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- | --- | ---: |",
        ]
    )
    for change in overhead_changes:
        percentage = f"{change.change_pct:+.1f}%" if change.change_pct is not None else "N/A (non-positive estimate)"
        flag = (" Potential regression" if change.regression else "") + (" Noisy estimate" if change.noisy else "")
        drift = f"{change.max_control_drift:.3f}" if change.max_control_drift is not None else "N/A"
        sections.append(
            f"| {change.scenario} | {change.concurrency} | {change.metric} | {change.base:.3f} | {change.candidate:.3f} | "
            f"{change.absolute_change:+.3f} | {percentage}{flag} | "
            f"{change.base_range[0]:.3f} to {change.base_range[1]:.3f} | "
            f"{change.candidate_range[0]:.3f} to {change.candidate_range[1]:.3f} | {drift} |"
        )
    sections.extend(
        [
            "",
            "Latency is in milliseconds; first_content_p50_ms measures the first non-empty text delta. Throughput is completed requests per second.",
            (
                f"Report only: warnings require more than {REGRESSION_PCT}% degradation and, for latency, more than {MIN_LATENCY_CHANGE_MS}ms. "
                "Inspect upstream changes and raw rounds before treating a warning as a gateway regression. "
                "The 1ms floor deliberately misses smaller overhead regressions; percentages near zero are unstable. "
                "Non-positive baseline overhead has no relative warning; noisy positive estimates may still warn. "
                "Throughput warnings use proxied RPS; derived throughput cost is descriptive."
            ),
            "",
            (
                "Raw per-request timings, commit identities, runner metadata and comparisons are retained in measurements.json. "
                "Shared runner results are useful for investigation, not an absolute service-level guarantee."
            ),
            "",
        ]
    )
    markdown = "\n".join(sections)
    (output / "summary.md").write_text(markdown, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as summary_file:
            summary_file.write(markdown)
    typer.echo(markdown)
    if any(change.regression for change in [*changes, *overhead_changes]):
        typer.echo("::warning::Potential gateway performance regression; inspect the performance summary and repeated measurements")


if __name__ == "__main__":
    app()
