from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console

from model_audit.diagnostics import difference_details, execution_display, feature_display, observation_summary, parity_display

if TYPE_CHECKING:
    from rich.status import Status

    from model_audit.models import Observation, Plan
    from model_audit.runner import ProgressEvent


class ConsoleProgress:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console(stderr=True)
        self.status: Status | None = None

    def start(self, plan: Plan, gateway_url: str, confirmations: int = 1) -> None:
        attempts = confirmations + 1
        maximum = plan.requests * attempts
        self.console.print(f"[bold]Model audit[/bold] | {len(plan.experiments)} experiments | up to {maximum} requests | {gateway_url}")

    def _stop(self) -> None:
        if self.status is not None:
            self.status.stop()
            self.status = None

    def _path(self, path: str, observation: Observation) -> None:
        self._stop()
        icon = {"success": "✓", "rejected": "○", "error": "✗", "inconclusive": "?"}[observation.outcome]
        detail = observation.error_code or observation.client_type or ""
        http = f" | HTTP {observation.http_status}" if observation.http_status is not None else ""
        self.console.print(f"  {icon} {observation.outcome.upper()} {path.title()} | {detail}{http} | {observation.duration_ms:.0f}ms")

    def __call__(self, event: ProgressEvent) -> None:
        if event.kind == "experiment_started":
            experiment = event.experiment
            self.console.print(f"\n[{event.index}/{event.total}] [bold]{experiment.target.model_id}[/bold]")
            self.console.print(f"      {experiment.case.id} | {experiment.transport} via {experiment.driver_id}")
        elif event.kind == "path_started" and event.path is not None:
            self._stop()
            self.status = self.console.status(f"  … {event.path.title()} attempt {event.attempt}/{event.max_attempts}")
            self.status.start()
        elif event.kind == "path_completed" and event.path is not None and event.observation is not None:
            self._path(event.path, event.observation)
        elif event.kind == "experiment_completed" and event.result is not None:
            self._stop()
            result = event.result
            self.console.print(f"  {parity_display(result.assessment).upper()}")
            self.console.print(f"  {feature_display(result.assessment).upper()}")
            if result.assessment.execution != "completed":
                self.console.print(f"  {execution_display(result.assessment).upper()}")
            if result.assessment.differences:
                for detail in difference_details(result):
                    self.console.print(f"    {detail.label}: direct={detail.direct} | gateway={detail.gateway}")
            if result.assessment.parity != "match" or result.assessment.execution != "completed":
                self.console.print(f"    Direct: {observation_summary(result.direct)}")
                self.console.print(f"    Gateway: {observation_summary(result.gateway)}")
