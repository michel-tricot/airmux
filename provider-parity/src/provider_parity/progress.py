from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape

from provider_parity.compare import oracle_failures
from provider_parity.diagnostics import difference_details, observation_summary

if TYPE_CHECKING:
    from rich.status import Status

    from provider_parity.models import Observation, Plan, Verdict
    from provider_parity.runner import ProgressEvent


OUTCOME_STYLE = {
    "success": ("✓ SUCCESS", "bold green"),
    "error": ("✗ ERROR", "bold red"),
    "inconclusive": ("? INCONCLUSIVE", "bold yellow"),
    "unsupported": ("○ UNSUPPORTED", "bold yellow"),
}

VERDICT_STYLE = {
    "parity": ("✓", "bold green"),
    "gateway_regression": ("✗", "bold red"),
    "different": ("≠", "bold red"),
    "gateway_only_success": ("↗", "bold cyan"),
    "inconclusive": ("?", "bold yellow"),
    "expected_difference": ("≈", "bold blue"),
}
MILLISECONDS_PER_SECOND = 1000


def _duration(observation: Observation) -> str | None:
    if observation.duration_ms is None:
        return None
    if observation.duration_ms >= MILLISECONDS_PER_SECOND:
        return f"{observation.duration_ms / MILLISECONDS_PER_SECOND:.2f}s"
    return f"{observation.duration_ms:.0f}ms"


def _details(observation: Observation) -> str:
    values = [observation.error_code, observation.sdk_type, _duration(observation)]
    return " | ".join(escape(value) for value in values if value)


def _path_name(path: str | None) -> str:
    return "Direct" if path == "direct" else "Gateway"


def _path_action(path: str | None) -> str:
    return "Calling provider directly" if path == "direct" else "Calling through AirLLM gateway"


def _verdict(verdict: Verdict) -> str:
    return verdict.replace("_", " ").upper()


class ConsoleProgress:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console(stderr=True)
        self.status: Status | None = None

    def start(self, plan: Plan, gateway_url: str, confirmations: int = 0) -> None:
        experiment_count = len(plan.experiments)
        experiment_label = "experiment" if experiment_count == 1 else "experiments"
        confirmation_label = (
            f" | up to {confirmations} confirmation pair{'s' if confirmations != 1 else ''} per suspected difference" if confirmations else ""
        )
        self.console.print(
            f"[bold]Provider parity[/bold] [dim]| {experiment_count} {experiment_label} | {plan.requests} requests{confirmation_label}"
            f" | {escape(gateway_url)}[/dim]"
        )

    def __call__(self, event: ProgressEvent) -> None:
        if event.kind == "experiment_started":
            target = event.experiment.target
            self.console.print()
            self.console.print(f"[bold cyan][{event.index}/{event.total}][/bold cyan] [bold]{escape(target.model_id)}[/bold]")
            self.console.print(
                f"      [dim]{escape(event.experiment.case.id)} | {event.experiment.transport} via {escape(event.experiment.driver_id)}[/dim]"
            )
            return
        if event.kind == "path_started":
            self._stop()
            confirmation = f" [dim](confirmation {event.attempt - 1}/{event.max_attempts - 1})[/dim]" if event.attempt > 1 else ""
            self.status = self.console.status(f"[bold]{_path_action(event.path)}[/bold]{confirmation}", spinner="dots")
            self.status.start()
            return
        if event.kind == "path_completed":
            self._stop()
            if event.observation is None:
                return
            label, style = OUTCOME_STYLE[event.observation.outcome]
            details = _details(event.observation)
            suffix = f" [dim]| {details}[/dim]" if details else ""
            confirmation = f" [dim](confirmation {event.attempt - 1}/{event.max_attempts - 1})[/dim]" if event.attempt > 1 else ""
            self.console.print(f"  [{style}]{label}[/{style}] {_path_name(event.path)}{confirmation}{suffix}")
            return
        self._experiment_completed(event)

    def _experiment_completed(self, event: ProgressEvent) -> None:
        self._stop()
        if event.result is None:
            return
        verdict = event.result.comparison.verdict
        icon, style = VERDICT_STYLE[verdict]
        self.console.print(f"  [{style}]{icon} {_verdict(verdict)}[/{style}]")
        comparison = event.result.comparison
        if event.result.confirmations:
            verdicts = ", ".join(attempt.comparison.verdict.replace("_", " ") for attempt in event.result.confirmations)
            self.console.print(f"    [dim]Confirmation verdicts: {escape(verdicts)}[/dim]")
        direct_support = comparison.direct_satisfies_oracle
        if direct_support is True:
            self.console.print("  [bold green]✓ PROVIDER FEATURE SUPPORTED[/bold green]")
        elif direct_support is False:
            self.console.print("  [bold yellow]○ PROVIDER FEATURE NOT SUPPORTED[/bold yellow]")
            for failure in oracle_failures(event.result.direct, event.experiment.case.oracle):
                self.console.print(f"    [yellow]{escape(failure)}[/yellow]")
            self.console.print(f"    [cyan]Provider behavior[/cyan]: {escape(observation_summary(event.result.direct))}")
        else:
            self.console.print("  [bold yellow]? PROVIDER FEATURE NOT EVALUATED[/bold yellow]")
            if event.result.direct.finish_reason in {"length", "max_tokens"}:
                self.console.print("    [yellow]output token limit reached before the feature oracle could be evaluated[/yellow]")
        if comparison.reason:
            self.console.print(f"    [dim]{escape(comparison.reason)}[/dim]")
        for detail in difference_details(event.result):
            self.console.print(f"    [bold]{escape(detail.label)}[/bold]: direct={escape(detail.direct)} | gateway={escape(detail.gateway)}")
        if comparison.reason or comparison.differences:
            self.console.print(f"    [cyan]Direct[/cyan]: {escape(observation_summary(event.result.direct))}")
            self.console.print(f"    [magenta]Gateway[/magenta]: {escape(observation_summary(event.result.gateway))}")

    def _stop(self) -> None:
        if self.status is not None:
            self.status.stop()
            self.status = None
