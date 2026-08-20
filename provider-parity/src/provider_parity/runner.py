from __future__ import annotations

import os
from collections import defaultdict
from hashlib import sha256

from provider_parity.compare import compare
from provider_parity.drivers import discover
from provider_parity.drivers.base import Connection
from provider_parity.gateway import LocalGateway
from provider_parity.models import ExpectedDifference, Experiment, PairResult, Plan


def _direct_connection(experiment: Experiment, api_key: str) -> Connection:
    target = experiment.target
    return Connection(base_url=target.base_url, api_key=api_key, auth=target.auth, headers=target.headers)


def _accepted(result: PairResult, expected: list[ExpectedDifference]) -> PairResult:
    difference = next((difference for difference in expected if difference.matches(result)), None)
    if difference is None or result.comparison.verdict in {"parity", "provider_limitation"}:
        return result
    return result.model_copy(
        update={"comparison": result.comparison.model_copy(update={"verdict": "expected_difference", "reason": difference.reason})}
    )


def execute(plan: Plan, expected: list[ExpectedDifference] | None = None) -> list[PairResult]:
    drivers = discover()
    grouped: dict[tuple[str, str], list[Experiment]] = defaultdict(list)
    for experiment in plan.experiments:
        grouped[(experiment.target.provider_id, experiment.target.surface_id)].append(experiment)
    results: list[PairResult] = []
    for experiments in grouped.values():
        targets = list({experiment.target.model_id: experiment.target for experiment in experiments}.values())
        credential_env = targets[0].credential_env
        api_key = os.environ.get(credential_env)
        if api_key is None:
            message = f"{credential_env} is not set for {targets[0].provider_id}"
            raise RuntimeError(message)
        with LocalGateway(targets) as gateway:
            for experiment in experiments:
                driver = drivers[experiment.driver_id]
                target = experiment.target
                direct = driver.execute(
                    _direct_connection(experiment, api_key), target.endpoint, target.upstream_model, experiment.case, experiment.transport
                )
                through_gateway = driver.execute(
                    gateway.connection(target.endpoint), target.endpoint, target.model_id, experiment.case, experiment.transport
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
                results.append(_accepted(result, expected or []))
    return results
