from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from model_audit.cases import fingerprint
from model_audit.compare import assess
from model_audit.drivers import discover
from model_audit.drivers.base import ClientDriver, Connection
from model_audit.models import Assessment, Experiment, Observation, PairAttempt, PairResult, Plan


class Gateway(Protocol):
    def require_ready(self) -> None: ...

    def connection(self, endpoint: str) -> Connection: ...


@dataclass(frozen=True)
class ProgressEvent:
    kind: Literal["experiment_started", "path_started", "path_completed", "experiment_completed"]
    index: int
    total: int
    experiment: Experiment
    path: Literal["direct", "gateway"] | None = None
    observation: Observation | None = None
    result: PairResult | None = None
    attempt: int = 1
    max_attempts: int = 1


type ProgressReporter = Callable[[ProgressEvent], None]


@dataclass(frozen=True)
class ExecutionOptions:
    confirmations: int = 1
    transient_retries: int = 2
    retry_backoff_seconds: float = 2
    request_timeout_seconds: float = 60
    concurrency: int = 4


DEFAULT_EXECUTION_OPTIONS = ExecutionOptions()
MAX_RETRY_DELAY_SECONDS = 60


@dataclass(frozen=True)
class RunContext:
    drivers: Mapping[str, ClientDriver]
    gateway: Gateway
    progress: ProgressReporter | None
    options: ExecutionOptions
    total: int


@dataclass(frozen=True)
class ScheduledExperiment:
    index: int
    experiment: Experiment
    api_key: str
    access_key: tuple[str, str, str]


@dataclass(frozen=True)
class PairContext:
    direct_driver: ClientDriver
    gateway_driver: ClientDriver
    direct_connection: Connection
    gateway: Gateway
    experiment: Experiment
    index: int
    total: int
    max_attempts: int
    progress: ProgressReporter | None


def _direct_connection(experiment: Experiment, api_key: str, timeout_seconds: float) -> Connection:
    target = experiment.target
    return Connection(
        base_url=target.base_url,
        api_key=api_key,
        auth=target.auth,
        headers=target.headers,
        route="direct",
        timeout_seconds=timeout_seconds,
        param_aliases=target.param_aliases,
    )


def _observe(driver: ClientDriver, connection: Connection, endpoint: str, experiment: Experiment, model: str) -> Observation:
    started = time.perf_counter()
    try:
        return driver.execute(connection, endpoint, model, experiment.case, experiment.transport)
    except Exception as error:  # noqa: BLE001 client boundaries must become reportable evidence
        return Observation(
            outcome="error",
            error_code="client_exception",
            error_message=str(error)[:500] or f"{type(error).__name__} raised without a message",
            duration_ms=(time.perf_counter() - started) * 1000,
            client_type=type(error).__name__,
        )


def _event(
    context: PairContext,
    kind: Literal["path_started", "path_completed"],
    path: Literal["direct", "gateway"],
    attempt: int,
    observation: Observation | None = None,
) -> ProgressEvent:
    return ProgressEvent(
        kind=kind,
        index=context.index,
        total=context.total,
        experiment=context.experiment,
        path=path,
        observation=observation,
        attempt=attempt,
        max_attempts=context.max_attempts,
    )


def _pair(context: PairContext, attempt: int) -> PairAttempt:
    if context.progress is not None:
        context.progress(_event(context, "path_started", "direct", attempt))
    direct = _observe(
        context.direct_driver,
        context.direct_connection,
        context.experiment.target.endpoint,
        context.experiment,
        context.experiment.target.upstream_model,
    )
    if context.progress is not None:
        context.progress(_event(context, "path_completed", "direct", attempt, direct))
        context.progress(_event(context, "path_started", "gateway", attempt))
    gateway = _observe(
        context.gateway_driver,
        context.gateway.connection(context.experiment.gateway_endpoint),
        context.experiment.gateway_endpoint,
        context.experiment,
        context.experiment.target.model_id,
    )
    if context.progress is not None:
        context.progress(_event(context, "path_completed", "gateway", attempt, gateway))
    return PairAttempt(direct=direct, gateway=gateway, assessment=assess(direct, gateway, context.experiment.case.oracle))


def _retry_transient(context: PairContext, previous: PairAttempt, attempt: int) -> PairAttempt:
    direct = previous.direct
    if direct.outcome == "transient":
        if context.progress is not None:
            context.progress(_event(context, "path_started", "direct", attempt))
        direct = _observe(
            context.direct_driver,
            context.direct_connection,
            context.experiment.target.endpoint,
            context.experiment,
            context.experiment.target.upstream_model,
        )
        if context.progress is not None:
            context.progress(_event(context, "path_completed", "direct", attempt, direct))
    gateway = previous.gateway
    if gateway.outcome == "transient":
        if context.progress is not None:
            context.progress(_event(context, "path_started", "gateway", attempt))
        gateway = _observe(
            context.gateway_driver,
            context.gateway.connection(context.experiment.gateway_endpoint),
            context.experiment.gateway_endpoint,
            context.experiment,
            context.experiment.target.model_id,
        )
        if context.progress is not None:
            context.progress(_event(context, "path_completed", "gateway", attempt, gateway))
    return PairAttempt(direct=direct, gateway=gateway, assessment=assess(direct, gateway, context.experiment.case.oracle))


def _with_transient_retries(context: PairContext, first_attempt: int, options: ExecutionOptions) -> tuple[PairAttempt, ...]:
    attempts = [_pair(context, first_attempt)]
    for retry in range(options.transient_retries):
        if attempts[-1].assessment.execution != "transient_failure":
            break
        if delay := min(MAX_RETRY_DELAY_SECONDS, options.retry_backoff_seconds * 2**retry):
            time.sleep(delay)
        attempts.append(_retry_transient(context, attempts[-1], first_attempt + retry + 1))
    return tuple(attempts)


def _confirmed(initial: PairAttempt, confirmations: tuple[PairAttempt, ...]) -> Assessment:
    assessments = tuple(attempt.assessment for attempt in (initial, *confirmations))
    first = assessments[0]
    stable = all(
        assessment.feature == first.feature
        and assessment.parity == first.parity
        and assessment.execution == first.execution
        and assessment.differences == first.differences
        for assessment in assessments[1:]
    )
    if stable:
        return first.model_copy(update={"reason": f"reproduced across {len(assessments)} attempts"})
    if any(assessment.execution == "transient_failure" for assessment in assessments):
        return Assessment(
            execution="transient_failure",
            feature=first.feature,
            parity="not_evaluated",
            reason="a transient failure prevented confirmation",
        )
    executions = {item.execution for item in assessments}
    execution = "harness_error" if "harness_error" in executions else "access_blocked" if "access_blocked" in executions else "completed"
    return Assessment(
        execution=execution,
        feature="unknown",
        parity="inconclusive",
        reason=f"classification changed across {len(assessments)} attempts",
    )


def _result(
    experiment: Experiment,
    attempt: PairAttempt,
    assessment: Assessment,
    attempts: tuple[PairAttempt, ...],
) -> PairResult:
    target = experiment.target
    return PairResult(
        case_id=experiment.case.id,
        case_version=experiment.case.version,
        case_fingerprint=fingerprint(experiment.case),
        claims=experiment.case.claims,
        provider_id=target.provider_id,
        surface_id=target.surface_id,
        endpoint=target.endpoint,
        gateway_surface_id=experiment.gateway_surface_id,
        gateway_endpoint=experiment.gateway_endpoint,
        model_id=target.model_id,
        upstream_model=target.upstream_model,
        client=(
            experiment.direct_driver_id
            if experiment.direct_driver_id == experiment.gateway_driver_id
            else f"{experiment.direct_driver_id}/{experiment.gateway_driver_id}"
        ),
        transport=experiment.transport,
        direct=attempt.direct,
        gateway=attempt.gateway,
        assessment=assessment,
        attempts=attempts,
    )


def _blocked_result(experiment: Experiment, code: str, message: str) -> PairResult:
    observation = Observation(outcome="inconclusive", error_code=code, error_message=message)
    attempt = PairAttempt(direct=observation, gateway=observation, assessment=assess(observation, observation, experiment.case.oracle))
    return _result(experiment, attempt, attempt.assessment, (attempt,))


def _harness_result(experiment: Experiment, error: Exception) -> PairResult:
    observation = Observation(
        outcome="error",
        error_code="client_exception",
        error_message=str(error)[:500] or f"{type(error).__name__} raised without a message",
        client_type=type(error).__name__,
    )
    attempt = PairAttempt(direct=observation, gateway=observation, assessment=assess(observation, observation, experiment.case.oracle))
    return _result(experiment, attempt, attempt.assessment, (attempt,))


def _progress_event(
    context: RunContext,
    kind: Literal["experiment_started", "experiment_completed"],
    scheduled: ScheduledExperiment,
    result: PairResult | None = None,
) -> None:
    if context.progress is not None:
        context.progress(
            ProgressEvent(
                kind=kind,
                index=scheduled.index,
                total=context.total,
                experiment=scheduled.experiment,
                result=result,
                max_attempts=(context.options.confirmations + 1) * (context.options.transient_retries + 1),
            )
        )


def _execute_experiment(scheduled: ScheduledExperiment, run: RunContext) -> PairResult:
    experiment = scheduled.experiment
    options = run.options
    context = PairContext(
        direct_driver=run.drivers[experiment.direct_driver_id],
        gateway_driver=run.drivers[experiment.gateway_driver_id],
        direct_connection=_direct_connection(experiment, scheduled.api_key, options.request_timeout_seconds),
        gateway=run.gateway,
        experiment=experiment,
        index=scheduled.index,
        total=run.total,
        max_attempts=(options.confirmations + 1) * (options.transient_retries + 1),
        progress=run.progress,
    )
    attempts = list(_with_transient_retries(context, 1, options))
    initial = attempts[-1]
    should_confirm = initial.assessment.execution == "completed" and (
        initial.assessment.parity != "match" or initial.assessment.feature != "supported"
    )
    confirmations = []
    for _ in range(options.confirmations if should_confirm else 0):
        confirmation_attempts = _with_transient_retries(context, len(attempts) + 1, options)
        attempts.extend(confirmation_attempts)
        confirmations.append(confirmation_attempts[-1])
    confirmed = tuple(confirmations)
    assessment = _confirmed(initial, confirmed) if confirmed else initial.assessment
    final = attempts[-1]
    return _result(experiment, final, assessment, tuple(attempts))


def _access_key(experiment: Experiment) -> tuple[str, str, str]:
    target = experiment.target
    return target.model_id, target.surface_id, experiment.gateway_surface_id


def _validate_options(options: ExecutionOptions) -> None:
    if options.concurrency < 1:
        message = "concurrency must be at least one"
        raise ValueError(message)
    if options.transient_retries < 0:
        message = "transient retries cannot be negative"
        raise ValueError(message)
    if options.retry_backoff_seconds < 0:
        message = "retry backoff cannot be negative"
        raise ValueError(message)


def _synchronized_progress(progress: ProgressReporter | None) -> ProgressReporter | None:
    if progress is None:
        return None
    lock = threading.Lock()

    def report(event: ProgressEvent) -> None:
        with lock:
            progress(event)

    return report


def _store_result(
    results: list[PairResult | None],
    index: int,
    result: PairResult,
    on_result: Callable[[PairResult], None] | None,
) -> None:
    results[index - 1] = result
    if on_result is not None:
        on_result(result)


def execute(
    plan: Plan,
    gateway: Gateway,
    *,
    progress: ProgressReporter | None = None,
    options: ExecutionOptions = DEFAULT_EXECUTION_OPTIONS,
    on_result: Callable[[PairResult], None] | None = None,
) -> list[PairResult]:
    _validate_options(options)
    drivers = discover()
    gateway.require_ready()
    total = len(plan.experiments)
    results: list[PairResult | None] = [None] * total
    pending = deque(enumerate(plan.experiments, start=1))
    blocked: dict[tuple[str, str, str], tuple[str, str]] = {}
    gateway_block: tuple[str, str] | None = None
    reporter = _synchronized_progress(progress)
    run = RunContext(drivers=drivers, gateway=gateway, progress=reporter, options=options, total=total)
    in_flight: dict[Future[PairResult], ScheduledExperiment] = {}
    with ThreadPoolExecutor(max_workers=options.concurrency, thread_name_prefix="model-audit") as executor:
        while pending or in_flight:
            while pending and len(in_flight) < options.concurrency:
                index, experiment = pending.popleft()
                target = experiment.target
                access_key = _access_key(experiment)
                block = gateway_block or blocked.get(access_key)
                api_key = os.environ.get(target.credential_env)
                if block is None and api_key is None:
                    block = ("direct_authentication", f"{target.credential_env} is not set")
                    blocked[access_key] = block
                if block is not None:
                    scheduled = ScheduledExperiment(index=index, experiment=experiment, api_key=api_key or "", access_key=access_key)
                    _progress_event(run, "experiment_started", scheduled)
                    result = _blocked_result(experiment, *block)
                    _store_result(results, index, result, on_result)
                    _progress_event(run, "experiment_completed", scheduled, result)
                    continue
                scheduled = ScheduledExperiment(index=index, experiment=experiment, api_key=cast("str", api_key), access_key=access_key)
                _progress_event(run, "experiment_started", scheduled)
                in_flight[executor.submit(_execute_experiment, scheduled, run)] = scheduled
            if not in_flight:
                continue
            completed, _ = wait(tuple(in_flight), return_when=FIRST_COMPLETED)
            for future in sorted(completed, key=lambda item: in_flight[item].index):
                scheduled = in_flight.pop(future)
                index = scheduled.index
                experiment = scheduled.experiment
                try:
                    result = future.result()
                except Exception as error:  # noqa: BLE001 worker failures must become reportable evidence
                    result = _harness_result(experiment, error)
                _store_result(results, index, result, on_result)
                if result.direct.error_code in {"direct_authentication", "direct_model_access"}:
                    blocked[scheduled.access_key] = (str(result.direct.error_code), "direct model access could not be established")
                if result.gateway.error_code == "gateway_authentication":
                    gateway_block = ("gateway_authentication", "gateway authentication could not be established")
                _progress_event(run, "experiment_completed", scheduled, result)
    return [cast("PairResult", result) for result in results]
