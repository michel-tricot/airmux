from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, Protocol

from provider_parity.compare import compare
from provider_parity.drivers import discover
from provider_parity.drivers.base import Connection, SDKDriver
from provider_parity.models import Comparison, ExpectedDifference, Experiment, Observation, PairAttempt, PairResult, Plan, Verdict


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
    confirmations: int = 0
    request_timeout_seconds: float = 60


DEFAULT_EXECUTION_OPTIONS = ExecutionOptions()


@dataclass(frozen=True)
class PairContext:
    driver: SDKDriver
    direct_connection: Connection
    gateway: Gateway
    experiment: Experiment
    index: int
    total: int
    max_attempts: int
    progress: ProgressReporter | None


@dataclass(frozen=True)
class AccessBlock:
    reason: str


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


def _accepted(result: PairResult, expected: list[ExpectedDifference]) -> PairResult:
    difference = next((difference for difference in expected if difference.matches(result)), None)
    if difference is None or result.comparison.verdict not in {"gateway_regression", "gateway_only_success", "different"}:
        return result
    return result.model_copy(
        update={"comparison": result.comparison.model_copy(update={"verdict": "expected_difference", "reason": difference.reason})}
    )


def _observe(driver: SDKDriver, connection: Connection, experiment: Experiment, model: str) -> Observation:
    started = time.perf_counter()
    try:
        return driver.execute(connection, experiment.target.endpoint, model, experiment.case, experiment.transport)
    except Exception as error:  # noqa: BLE001 vendor SDK exceptions are parity evidence for one path
        return Observation(
            outcome="error",
            error_code="sdk_exception",
            error_message=str(error)[:500] or f"{type(error).__name__} raised without a message",
            duration_ms=(time.perf_counter() - started) * 1000,
            sdk_type=type(error).__name__,
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
    through_gateway = _observe(
        context.driver,
        context.gateway.connection(context.experiment.target.endpoint),
        context.experiment,
        context.experiment.target.model_id,
    )
    if context.progress is not None:
        context.progress(_event(context, "path_completed", "gateway", attempt, through_gateway))
    return PairAttempt(
        direct=direct,
        gateway=through_gateway,
        comparison=compare(direct, through_gateway, context.experiment.case.oracle),
    )


def _common_status(comparisons: tuple[Comparison, ...], name: Literal["direct_satisfies_oracle", "gateway_satisfies_oracle"]) -> bool | None:
    values = tuple(getattr(comparison, name) for comparison in comparisons)
    return values[0] if all(value == values[0] for value in values) else None


def _confirmed(initial: PairAttempt, confirmations: tuple[PairAttempt, ...]) -> Comparison:
    attempts = (initial, *confirmations)
    comparisons = tuple(attempt.comparison for attempt in attempts)
    attempt_count = len(attempts)
    first = comparisons[0]
    same_classification = all(comparison.verdict == first.verdict and comparison.differences == first.differences for comparison in comparisons[1:])
    if same_classification:
        return first.model_copy(update={"reason": f"reproduced across {attempt_count} attempts"})
    stable_differences = tuple(
        difference for difference in first.differences if difference != "oracle" and all(difference in item.differences for item in comparisons[1:])
    )
    direct_status = _common_status(comparisons, "direct_satisfies_oracle")
    gateway_status = _common_status(comparisons, "gateway_satisfies_oracle")
    if stable_differences:
        if all(attempt.direct.outcome == "success" and attempt.gateway.outcome != "success" for attempt in attempts):
            verdict: Verdict = "gateway_regression"
        elif all(attempt.direct.outcome != "success" and attempt.gateway.outcome == "success" for attempt in attempts):
            verdict = "gateway_only_success"
        else:
            verdict = "different"
        return Comparison(
            verdict=verdict,
            differences=stable_differences,
            reason=f"reproduced across {attempt_count} attempts",
            direct_satisfies_oracle=direct_status,
            gateway_satisfies_oracle=gateway_status,
        )
    return Comparison(
        verdict="inconclusive",
        reason=f"suspected parity difference did not reproduce across {attempt_count} attempts",
        direct_satisfies_oracle=direct_status,
        gateway_satisfies_oracle=gateway_status,
    )


def _access_block(attempt: PairAttempt) -> AccessBlock | None:
    if attempt.direct.error_code in {"direct_authentication", "direct_model_access"}:
        return AccessBlock(reason="not run because direct model access could not be established earlier")
    if attempt.gateway.error_code == "gateway_authentication":
        return AccessBlock(reason="not run because gateway authentication failed earlier")
    return None


def _result(
    experiment: Experiment,
    attempt: PairAttempt,
    comparison: Comparison,
    confirmations: tuple[PairAttempt, ...] = (),
) -> PairResult:
    target = experiment.target
    return PairResult(
        case_id=experiment.case.id,
        case_version=experiment.case.version,
        case_fingerprint=sha256(experiment.case.model_dump_json().encode()).hexdigest()[:16],
        provider_id=target.provider_id,
        surface_id=target.surface_id,
        endpoint=target.endpoint,
        model_id=target.model_id,
        upstream_model=target.upstream_model,
        sdk=experiment.driver_id,
        transport=experiment.transport,
        direct=attempt.direct,
        gateway=attempt.gateway,
        comparison=comparison,
        confirmations=confirmations,
    )


def _not_run(experiment: Experiment, access_block: AccessBlock) -> PairResult:
    observation = Observation(outcome="inconclusive", error_code="not_run", error_message=access_block.reason)
    attempt = PairAttempt(
        direct=observation,
        gateway=observation,
        comparison=Comparison(
            verdict="inconclusive",
            reason=access_block.reason,
            direct_satisfies_oracle=None,
            gateway_satisfies_oracle=None,
        ),
    )
    return _result(experiment, attempt, attempt.comparison)


def execute(
    plan: Plan,
    gateway: Gateway,
    expected: list[ExpectedDifference] | None = None,
    *,
    progress: ProgressReporter | None = None,
    options: ExecutionOptions = DEFAULT_EXECUTION_OPTIONS,
) -> list[PairResult]:
    drivers = discover()
    gateway.require_ready()
    results: list[PairResult] = []
    access_blocks: dict[tuple[str, str, str], AccessBlock] = {}
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
        credential_env = target.credential_env
        api_key = os.environ.get(credential_env)
        if api_key is None:
            message = f"{credential_env} is not set for {target.provider_id}"
            raise RuntimeError(message)
        driver = drivers[experiment.driver_id]
        access_key = (target.model_id, target.surface_id, experiment.driver_id)
        access_block = access_blocks.get(access_key)
        if access_block is not None:
            result = _not_run(experiment, access_block)
            results.append(result)
            if progress is not None:
                progress(ProgressEvent(kind="experiment_completed", index=index, total=total, experiment=experiment, result=result))
            continue
        context = PairContext(
            driver=driver,
            direct_connection=_direct_connection(experiment, api_key, options.request_timeout_seconds),
            gateway=gateway,
            experiment=experiment,
            index=index,
            total=total,
            max_attempts=options.confirmations + 1,
            progress=progress,
        )
        initial = _pair(context, 1)
        if initial.comparison.verdict in {"gateway_regression", "gateway_only_success", "different"}:
            confirmations_tuple = tuple(_pair(context, attempt) for attempt in range(2, options.confirmations + 2))
        else:
            confirmations_tuple = ()
        comparison = _confirmed(initial, confirmations_tuple) if confirmations_tuple else initial.comparison
        access_block = _access_block(initial)
        if access_block is not None:
            access_blocks[access_key] = access_block
        result = _result(experiment, initial, comparison, confirmations_tuple)
        result = _accepted(result, expected or [])
        results.append(result)
        if progress is not None:
            progress(ProgressEvent(kind="experiment_completed", index=index, total=total, experiment=experiment, result=result))
    return results
