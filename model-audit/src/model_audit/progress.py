from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from model_audit.diagnostics import difference_details, execution_display, feature_display, observation_summary, parity_display

if TYPE_CHECKING:
    from rich.progress import TaskID
    from rich.status import Status

    from model_audit.models import Observation, Plan
    from model_audit.runner import ProgressEvent


class ConsoleProgress:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console(stderr=True)
        self.status: Status | None = None
        self.parallel = False
        self.progress: Progress | None = None
        self.tasks: dict[int, TaskID] = {}
        self.completed = 0
        self.lock = threading.RLock()

    def start(self, plan: Plan, gateway_url: str, confirmations: int = 1, concurrency: int = 1) -> None:
        attempts = confirmations + 1
        maximum = plan.requests * attempts
        self.parallel = concurrency > 1
        self.console.print(
            f"[bold]Model audit[/bold] | {len(plan.experiments)} experiments | up to {maximum} requests | concurrency {concurrency} | {gateway_url}"
        )

    def _stop(self) -> None:
        if self.status is not None:
            self.status.stop()
            self.status = None

    @staticmethod
    def _path_text(path: str, observation: Observation) -> str:
        icon = {"success": "✓", "rejected": "○", "error": "✗", "inconclusive": "?"}[observation.outcome]
        detail = observation.error_code or observation.client_type or ""
        http = f" | HTTP {observation.http_status}" if observation.http_status is not None else ""
        return f"{icon} {observation.outcome.upper()} {path.title()} | {detail}{http} | {observation.duration_ms:.0f}ms"

    def _path(self, path: str, observation: Observation) -> None:
        self._stop()
        self.console.print(f"  {self._path_text(path, observation)}")

    @staticmethod
    def _label(event: ProgressEvent, phase: str) -> str:
        experiment = event.experiment
        return f"[{event.index}/{event.total}] {experiment.target.model_id} | {experiment.case.id} | {phase}"

    def _parallel_progress(self) -> Progress:
        if self.progress is None:
            self.progress = Progress(SpinnerColumn(), TextColumn("{task.description}"), console=self.console, transient=True)
            self.progress.start()
        return self.progress

    def _result(self, event: ProgressEvent, prefix: str = "  ") -> None:
        if event.result is None:
            return
        result = event.result
        self.console.print(f"{prefix}{parity_display(result.assessment).upper()}")
        self.console.print(f"{prefix}{feature_display(result.assessment).upper()}")
        if result.assessment.execution != "completed":
            self.console.print(f"{prefix}{execution_display(result.assessment).upper()}")
        if result.assessment.differences:
            for detail in difference_details(result):
                self.console.print(f"{prefix}  {detail.label}: direct={detail.direct} | gateway={detail.gateway}")
        if result.assessment.parity != "match" or result.assessment.execution != "completed":
            self.console.print(f"{prefix}  Direct: {observation_summary(result.direct)}")
            self.console.print(f"{prefix}  Gateway: {observation_summary(result.gateway)}")

    def _parallel(self, event: ProgressEvent) -> None:
        progress = self._parallel_progress()
        if event.kind == "experiment_started":
            self.tasks[event.index] = progress.add_task(self._label(event, "queued"), total=None)
        elif event.kind == "path_started" and event.path is not None:
            progress.update(self.tasks[event.index], description=self._label(event, f"{event.path.title()} {event.attempt}/{event.max_attempts}"))
        elif event.kind == "path_completed" and event.path is not None and event.observation is not None:
            progress.console.print(f"[{event.index}/{event.total}] {self._path_text(event.path, event.observation)}")
            progress.update(self.tasks[event.index], description=self._label(event, "comparing"))
        elif event.kind == "experiment_completed" and event.result is not None:
            progress.remove_task(self.tasks.pop(event.index))
            progress.console.print(f"[{event.index}/{event.total}] [bold]{event.experiment.target.model_id}[/bold] | {event.experiment.case.id}")
            self._result(event)
            self.completed += 1
            if self.completed == event.total:
                progress.stop()
                self.progress = None

    def __call__(self, event: ProgressEvent) -> None:
        with self.lock:
            if self.parallel:
                self._parallel(event)
            elif event.kind == "experiment_started":
                experiment = event.experiment
                self.console.print(f"\n[{event.index}/{event.total}] [bold]{experiment.target.model_id}[/bold]")
                self.console.print(
                    f"      {experiment.case.id} | {experiment.transport} | "
                    f"{experiment.target.surface_id} via {experiment.direct_driver_id} -> "
                    f"{experiment.gateway_surface_id} via {experiment.gateway_driver_id}"
                )
            elif event.kind == "path_started" and event.path is not None:
                self._stop()
                self.status = self.console.status(f"  … {event.path.title()} attempt {event.attempt}/{event.max_attempts}")
                self.status.start()
            elif event.kind == "path_completed" and event.path is not None and event.observation is not None:
                self._path(event.path, event.observation)
            elif event.kind == "experiment_completed" and event.result is not None:
                self._stop()
                self._result(event)
