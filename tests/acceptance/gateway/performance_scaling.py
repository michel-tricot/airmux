from __future__ import annotations

import json
import os
import platform
import statistics
from itertools import product
from pathlib import Path  # noqa: TC003 Typer resolves CLI annotations at runtime
from typing import Annotated, Literal, Self

import typer
from performance import OVERHEAD_METHOD, OverheadMeasurement, ProviderProtocol, Settings, run_revision
from pydantic import BaseModel, ConfigDict, model_validator

app = typer.Typer()


class ScalingCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workers: Literal[1, 2, 4]
    max_connections: Literal[100, 256]
    concurrency: Literal[32, 128]
    protocol: ProviderProtocol


CASES = tuple(
    ScalingCase(workers=workers, max_connections=connections, concurrency=concurrency, protocol=protocol)
    for workers, connections, concurrency, protocol in product((1, 2, 4), (100, 256), (32, 128), ("http1", "http2"))
)


class ScalingMeasurement(BaseModel):
    case: ScalingCase
    overhead: OverheadMeasurement

    @model_validator(mode="after")
    def matching_workload(self) -> Self:
        measured = self.overhead.proxied
        if (measured.concurrency, measured.provider_protocol, measured.scenario, measured.revision) != (
            self.case.concurrency,
            self.case.protocol,
            "buffered_devnull",
            "candidate",
        ):
            message = "Scaling case must match its measured candidate workload"
            raise ValueError(message)
        return self


def summarize(measurements: list[ScalingMeasurement]) -> list[dict[str, object]]:
    identities = [(measurement.case, measurement.overhead.proxied.round) for measurement in measurements]
    if len(identities) != len(set(identities)):
        message = "Scaling measurements cannot contain duplicate case rounds"
        raise ValueError(message)
    summaries = []
    for case in CASES:
        matching = [measurement.overhead for measurement in measurements if measurement.case == case]
        if not matching:
            continue
        resources = [measurement.proxied.resources for measurement in matching]
        if any(resource is None for resource in resources):
            message = "Scaling measurements require process and connection observations"
            raise ValueError(message)
        summaries.append(
            {
                **case.model_dump(),
                "rounds": len(matching),
                **{
                    metric: statistics.median(measurement.proxied.metrics()[metric] for measurement in matching)
                    for metric in matching[0].proxied.metrics()
                },
                **{metric: statistics.median(measurement.metrics()[metric] for measurement in matching) for metric in matching[0].metrics()},
                "gateway_cpu_cores": statistics.median(
                    resource.cpu_seconds["gateway"] / resource.elapsed_s for resource in resources if resource is not None
                ),
                "provider_cpu_cores": statistics.median(
                    resource.cpu_seconds["provider"] / resource.elapsed_s for resource in resources if resource is not None
                ),
                "client_cpu_cores": statistics.median(
                    resource.cpu_seconds["client"] / resource.elapsed_s for resource in resources if resource is not None
                ),
                "provider_connections": statistics.median(resource.provider_connections for resource in resources if resource is not None),
                "control_drift_ms": max(measurement.control_drift("overhead_mean_ms") for measurement in matching),
            }
        )
    return summaries


@app.command()
def benchmark(  # noqa: PLR0913 CLI flags define the scaling experiment
    *,
    candidate_bin: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    candidate_revision: Annotated[str, typer.Option()],
    output: Annotated[Path, typer.Option()],
    rounds: Annotated[int, typer.Option(min=1)] = 3,
    duration_s: Annotated[float, typer.Option(min=0.1)] = 2,
    warmup: Annotated[int, typer.Option(min=1)] = 20,
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    measurements: list[ScalingMeasurement] = []
    for round_number in range(1, rounds + 1):
        for index, case in enumerate(CASES if round_number % 2 else tuple(reversed(CASES))):
            typer.echo(f"Round {round_number}/{rounds}: {case}")
            settings = Settings(
                duration_s,
                warmup,
                0,
                scenario="buffered_devnull",
                workers=case.workers,
                max_connections=case.max_connections,
                concurrency=case.concurrency,
                provider_protocol=case.protocol,
                observe_resources=True,
            )
            result = run_revision(output / f"round-{round_number}-case-{index}", candidate_bin, "candidate", round_number, settings)
            (overhead,) = result.overhead
            measurements.append(ScalingMeasurement(case=case, overhead=overhead))
            (output / "measurements.json").write_text(
                json.dumps(
                    {
                        "candidate_revision": candidate_revision,
                        "platform": platform.platform(),
                        "python": platform.python_version(),
                        "cpu_count": os.cpu_count(),
                        "duration_s": duration_s,
                        "warmup": warmup,
                        "keepalive_connections_per_worker": 20,
                        "overhead_methodology": OVERHEAD_METHOD,
                        "resource_methodology": (
                            "CPU seconds are process-time deltas over warmup and load, divided by that window's wall time. "
                            "Gateway CPU includes its worker processes; client CPU excludes children. "
                            "Provider connections count distinct client addresses used for inference during warmup and load, including churn. "
                            "HTTP/2 direct controls multiplex over one connection; proxied traffic can use one per gateway worker. "
                            "CPU and connection observations run outside request timing; the provider tracks addresses only, not payloads."
                        ),
                        "measurements": [measurement.model_dump(mode="json") for measurement in measurements],
                        "summary": summarize(measurements),
                    },
                    indent=2,
                )
                + "\n"
            )
    summaries = summarize(measurements)
    columns = (
        "workers",
        "max_connections",
        "concurrency",
        "protocol",
        "requests_per_second",
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "overhead_mean_ms",
        "direct_requests_per_second",
        "gateway_cpu_cores",
        "provider_cpu_cores",
        "client_cpu_cores",
        "provider_connections",
    )
    lines = ["# Gateway worker and pool scaling", "", "| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for summary in summaries:
        values = [f"{value:.3f}" if isinstance(value, float) else str(value) for value in (summary[column] for column in columns)]
        lines.append("| " + " | ".join(values) + " |")
    (output / "summary.md").write_text("\n".join(lines) + "\n")
    typer.echo(f"Wrote {output / 'measurements.json'} and {output / 'summary.md'}")


if __name__ == "__main__":
    app()
