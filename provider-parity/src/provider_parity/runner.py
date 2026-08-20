from __future__ import annotations

import os
from hashlib import sha256
from typing import TYPE_CHECKING

from provider_parity.compare import compare
from provider_parity.drivers import discover
from provider_parity.drivers.base import Connection
from provider_parity.models import ExpectedDifference, Experiment, PairResult, Plan

if TYPE_CHECKING:
    from provider_parity.gateway import Gateway


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


def execute(plan: Plan, gateway: Gateway, expected: list[ExpectedDifference] | None = None) -> list[PairResult]:
    drivers = discover()
    gateway.require_ready()
    results: list[PairResult] = []
    for experiment in plan.experiments:
        target = experiment.target
        credential_env = target.credential_env
        api_key = os.environ.get(credential_env)
        if api_key is None:
            message = f"{credential_env} is not set for {target.provider_id}"
            raise RuntimeError(message)
        driver = drivers[experiment.driver_id]
        direct = driver.execute(
            _direct_connection(experiment, api_key), target.endpoint, target.upstream_model, experiment.case, experiment.transport
        )
        through_gateway = driver.execute(gateway.connection(target.endpoint), target.endpoint, target.model_id, experiment.case, experiment.transport)
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
        results.append(_accepted(result, expected or []))
    return results
