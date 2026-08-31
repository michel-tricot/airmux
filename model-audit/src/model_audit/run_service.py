from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from model_audit.models import PairResult, Plan, ReportDocument, ReportPaths, RunMetadata, RunSettings
from model_audit.progress import ConsoleProgress
from model_audit.report import archive_plan, checkpoint_interval, ordered_results, write_checkpoint, write_report
from model_audit.runner import ExecutionOptions, execute

if TYPE_CHECKING:
    from pathlib import Path

    from model_audit.gateway import Gateway


@dataclass(frozen=True)
class RunContext:
    plan: Plan
    gateway: Gateway
    run: RunMetadata
    settings: RunSettings
    concurrency: int
    directory: Path


def execute_checkpointed(
    pending: Plan,
    existing: tuple[PairResult, ...],
    context: RunContext,
) -> tuple[tuple[PairResult, ...], ReportPaths]:
    accumulated = list(existing)
    interval = checkpoint_interval(len(context.plan.experiments))

    def document(complete: bool) -> ReportDocument:
        return ReportDocument(
            run=context.run,
            plan=archive_plan(context.plan),
            settings=context.settings,
            complete=complete,
            results=ordered_results(context.plan, tuple(accumulated)),
        )

    write_report(document(False), context.directory)

    def checkpoint(result: PairResult) -> None:
        accumulated.append(result)
        if not len(accumulated) % interval:
            write_checkpoint(document(False), context.directory)

    progress = ConsoleProgress()
    progress.start(
        pending,
        context.gateway.base_url,
        context.settings.confirmations,
        context.settings.transient_retries,
        context.concurrency,
    )
    execute(
        pending,
        context.gateway,
        progress=progress,
        options=ExecutionOptions(
            confirmations=context.settings.confirmations,
            transient_retries=context.settings.transient_retries,
            retry_backoff_seconds=context.settings.retry_backoff_seconds,
            request_timeout_seconds=context.settings.request_timeout_seconds,
            concurrency=context.concurrency,
        ),
        on_result=checkpoint,
    )
    results = ordered_results(context.plan, tuple(accumulated))
    paths = write_report(document(True), context.directory)
    return results, paths
