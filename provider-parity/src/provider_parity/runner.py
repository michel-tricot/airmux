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
from provider_parity.models import ExpectedDifference, Experiment, Observation, PairResult, Plan


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


type ProgressReporter = Callable[[ProgressEvent], None]


def _direct_connection(experiment: Experiment, api_key: str) -> Connection:
    target = experiment.target
    return Connection(base_url=target.base_url, api_key=api_key, auth=target.auth, headers=target.headers, route="direct")


def _accepted(result: PairResult, expected: list[ExpectedDifference]) -> PairResult:
    difference = next((difference for difference in expected if difference.matches(result)), None)
    if difference is None or result.comparison.verdict in {"parity", "provider_limitation"}:
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


def execute(
    plan: Plan,
    gateway: Gateway,
    expected: list[ExpectedDifference] | None = None,
    *,
    progress: ProgressReporter | None = None,
) -> list[PairResult]:
    drivers = discover()
    gateway.require_ready()
    results: list[PairResult] = []
    total = len(plan.experiments)
    for index, experiment in enumerate(plan.experiments, start=1):
        if progress is not None:
            progress(ProgressEvent(kind="experiment_started", index=index, total=total, experiment=experiment))
        target = experiment.target
        credential_env = target.credential_env
        api_key = os.environ.get(credential_env)
        if api_key is None:
            message = f"{credential_env} is not set for {target.provider_id}"
            raise RuntimeError(message)
        driver = drivers[experiment.driver_id]
        if progress is not None:
            progress(ProgressEvent(kind="path_started", index=index, total=total, experiment=experiment, path="direct"))
        direct = _observe(driver, _direct_connection(experiment, api_key), experiment, target.upstream_model)
        if progress is not None:
            progress(ProgressEvent(kind="path_completed", index=index, total=total, experiment=experiment, path="direct", observation=direct))
            progress(ProgressEvent(kind="path_started", index=index, total=total, experiment=experiment, path="gateway"))
        through_gateway = _observe(driver, gateway.connection(target.endpoint), experiment, target.model_id)
        if progress is not None:
            progress(
                ProgressEvent(kind="path_completed", index=index, total=total, experiment=experiment, path="gateway", observation=through_gateway)
            )
        result = PairResult(
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
            direct=direct,
            gateway=through_gateway,
            comparison=compare(direct, through_gateway, experiment.case.oracle),
        )
        result = _accepted(result, expected or [])
        results.append(result)
        if progress is not None:
            progress(ProgressEvent(kind="experiment_completed", index=index, total=total, experiment=experiment, result=result))
    return results
