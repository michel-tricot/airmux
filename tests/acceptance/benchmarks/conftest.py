"""Shared benchmark helper: run a call many times, then render the distribution as a table.

Every benchmark uses the `bench` fixture so they all warm up, sample and report the same way.
Measure a cost as a difference against a baseline (see benchmarks/test_overhead.py); the table
shows each series and, when a baseline and treatment are named, the per-percentile overhead row.
"""

from __future__ import annotations

import statistics
import time
from typing import TYPE_CHECKING

import pytest
from rich import box
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from collections.abc import Callable

PERCENTILES = (50, 90, 99)


def _pct(xs: list[float], q: float) -> float:
    ordered = sorted(xs)
    rank = max(0, min(len(ordered) - 1, round(q / 100 * len(ordered)) - 1))
    return ordered[rank]


class Bench:
    """Collects named timing series (milliseconds) and prints them as one rich table."""

    def __init__(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._capsys = capsys
        self._series: dict[str, list[float]] = {}

    def measure(self, name: str, call: Callable[[], object], *, warmup: int = 20, samples: int = 200) -> None:
        times: list[float] = []
        for i in range(warmup + samples):
            start = time.perf_counter()
            resp = call()
            elapsed = (time.perf_counter() - start) * 1000
            assert getattr(resp, "status_code", 200) == 200
            if i >= warmup:
                times.append(elapsed)
        self._series[name] = times

    def pct(self, name: str, q: float) -> float:
        return _pct(self._series[name], q)

    def overhead(self, treatment: str, baseline: str, q: float = 50) -> float:
        return _pct(self._series[treatment], q) - _pct(self._series[baseline], q)

    def report(self, *, title: str, baseline: str | None = None, treatment: str | None = None) -> None:
        table = Table(title=title, box=box.ROUNDED, header_style="bold", title_style="bold", caption="latency in milliseconds")
        table.add_column("series", style="cyan", no_wrap=True)
        table.add_column("n", justify="right")
        for q in PERCENTILES:
            table.add_column(f"p{q}", justify="right")
        table.add_column("max", justify="right")
        table.add_column("mean", justify="right")
        for name, xs in self._series.items():
            cells = [f"{_pct(xs, q):.2f}" for q in PERCENTILES] + [f"{max(xs):.2f}", f"{statistics.fmean(xs):.2f}"]
            table.add_row(name, str(len(xs)), *cells)
        if baseline and treatment:
            base, treat = self._series[baseline], self._series[treatment]
            deltas = [f"{_pct(treat, q) - _pct(base, q):.2f}" for q in PERCENTILES] + ["", f"{statistics.fmean(treat) - statistics.fmean(base):.2f}"]
            table.add_section()
            table.add_row("overhead", "", *deltas, style="bold magenta")
        with self._capsys.disabled():
            Console().print(table)


@pytest.fixture
def bench(capsys: pytest.CaptureFixture[str]) -> Bench:
    return Bench(capsys)
