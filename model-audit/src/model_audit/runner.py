from __future__ import annotations

import os
import time
from collections.abc import Callable
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
    request_timeout_seconds: float = 60


DEFAULT_EXECUTION_OPTIONS = ExecutionOptions()


@dataclass(frozen=True)
class PairContext:
    driver: ClientDriver
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
    )


def _observe(driver: ClientDriver, connection: Connection, experiment: Experiment, model: str) -> Observation:
    started = time.perf_counter()
    try:
        return driver.execute(connection, experiment.target.endpoint, model, experiment.case, experiment.transport)
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
    direct = _observe(context.driver, context.direct_connection, context.experiment, context.experiment.target.upstream_model)
    if context.progress is not None:
        context.progress(_event(context, "path_completed", "direct", attempt, direct))
        context.progress(_event(context, "path_started", "gateway", attempt))
    gateway = _observe(
        context.driver,
        context.gateway.connection(context.experiment.target.endpoint),
        context.experiment,
        context.experiment.target.model_id,
    )
    if context.progress is not None:
        context.progress(_event(context, "path_completed", "gateway", attempt, gateway))
    return PairAttempt(direct=direct, gateway=gateway, assessment=assess(direct, gateway, context.experiment.case.oracle))


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
    confirmations: tuple[PairAttempt, ...] = (),
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
        model_id=target.model_id,
        upstream_model=target.upstream_model,
        client=experiment.driver_id,
        transport=experiment.transport,
        direct=attempt.direct,
        gateway=attempt.gateway,
        assessment=assessment,
        confirmations=confirmations,
    )


def _blocked_result(experiment: Experiment, code: str, message: str) -> PairResult:
    observation = Observation(outcome="inconclusive", error_code=code, error_message=message)
    attempt = PairAttempt(direct=observation, gateway=observation, assessment=assess(observation, observation, experiment.case.oracle))
    return _result(experiment, attempt, attempt.assessment)


def execute(
    plan: Plan,
    gateway: Gateway,
    *,
    progress: ProgressReporter | None = None,
    options: ExecutionOptions = DEFAULT_EXECUTION_OPTIONS,
) -> list[PairResult]:
    drivers = discover()
    gateway.require_ready()
    results = []
    blocked: dict[tuple[str, str, str], tuple[str, str]] = {}
    total = len(plan.experiments)
    for index, experiment in enumerate(plan.experiments, start=1):
        if progress is not None:
            progress(
                ProgressEvent(
                    kind="experiment_started",
                    index=index,
                    total=total,
                    experiment=experiment,
                    max_attempts=options.confirmations + 1,
                )
            )
        target = experiment.target
        access_key = (target.model_id, target.surface_id, experiment.driver_id)
        block = blocked.get(access_key)
        api_key = os.environ.get(target.credential_env)
        if block is None and api_key is None:
            block = ("direct_authentication", f"{target.credential_env} is not set")
            blocked[access_key] = block
        if block is not None:
            result = _blocked_result(experiment, *block)
        else:
            context = PairContext(
                driver=drivers[experiment.driver_id],
                direct_connection=_direct_connection(experiment, cast("str", api_key), options.request_timeout_seconds),
                gateway=gateway,
                experiment=experiment,
                index=index,
                total=total,
                max_attempts=options.confirmations + 1,
                progress=progress,
            )
            initial = _pair(context, 1)
            should_confirm = initial.assessment.parity != "match" or initial.assessment.feature != "supported"
            confirmations = tuple(_pair(context, attempt) for attempt in range(2, options.confirmations + 2)) if should_confirm else ()
            assessment = _confirmed(initial, confirmations) if confirmations else initial.assessment
            if initial.direct.error_code in {"direct_authentication", "direct_model_access"}:
                blocked[access_key] = (str(initial.direct.error_code), "direct model access could not be established")
            if initial.gateway.error_code == "gateway_authentication":
                blocked[access_key] = ("gateway_authentication", "gateway authentication could not be established")
            result = _result(experiment, initial, assessment, confirmations)
        results.append(result)
        if progress is not None:
            progress(ProgressEvent(kind="experiment_completed", index=index, total=total, experiment=experiment, result=result))
    return results
