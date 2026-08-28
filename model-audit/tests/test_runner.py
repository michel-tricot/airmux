from __future__ import annotations

import threading

from model_audit import runner
from model_audit.drivers.base import ClientDriver, Connection, status_outcome
from model_audit.models import Experiment, Observation, Plan
from tests.helpers import case, target


class Gateway:
    def require_ready(self) -> None:
        return

    def connection(self, endpoint: str) -> Connection:
        return Connection(base_url="http://gateway/inf/v1", api_key="gateway", auth="bearer", headers={}, route="gateway")


class SequenceDriver(ClientDriver):
    id = "sequence"
    mode = "api"
    endpoints = frozenset({"chat/completions"})

    def __init__(self, observations: tuple[Observation, ...]) -> None:
        self.observations = iter(observations)

    def execute(self, connection, endpoint, model, case, transport):
        return next(self.observations)


class EndpointDriver(ClientDriver):
    id = "endpoint"
    mode = "api"
    endpoints = frozenset({"chat/completions", "messages"})

    def execute(self, connection, endpoint, model, case, transport):
        return Observation(outcome="success", text="ok", client_type=endpoint)


class ConcurrentDriver(ClientDriver):
    id = "concurrent"
    mode = "api"
    endpoints = frozenset({"chat/completions"})

    def __init__(self) -> None:
        self.barrier = threading.Barrier(2)
        self.lock = threading.Lock()
        self.active = 0
        self.maximum_active = 0

    def execute(self, connection, endpoint, model, case, transport):
        with self.lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        try:
            self.barrier.wait(timeout=1)
        except threading.BrokenBarrierError:
            pass
        finally:
            with self.lock:
                self.active -= 1
        return Observation(outcome="success", text="ok", client_type=model)


class GatewayAuthDriver(ClientDriver):
    id = "gateway-auth"
    mode = "api"
    endpoints = frozenset({"chat/completions"})

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.direct_calls = 0

    def execute(self, connection, endpoint, model, case, transport):
        if connection.route == "gateway":
            return Observation(outcome="inconclusive", error_code="gateway_authentication", http_status=401)
        with self.lock:
            self.direct_calls += 1
        return Observation(outcome="success", text="ok")


def experiment(model_id: str, driver_id: str = "concurrent", provider_id: str = "stub") -> Experiment:
    return Experiment(
        target=target(provider_id=provider_id, model_id=model_id),
        case=case(),
        direct_driver_id=driver_id,
        gateway_driver_id=driver_id,
        gateway_surface_id="oai",
        gateway_endpoint="chat/completions",
        transport="buffered",
    )


def test_runner_confirms_and_reports_a_gateway_gap(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    direct = Observation(outcome="success", text="ok")
    gateway = Observation(outcome="rejected", http_status=400, error_code="invalid_request_error", error_message="bad request")
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver((direct, gateway, direct, gateway))})
    experiment = Experiment(
        target=target(),
        case=case(),
        direct_driver_id="sequence",
        gateway_driver_id="sequence",
        gateway_surface_id="oai",
        gateway_endpoint="chat/completions",
        transport="buffered",
    )

    result = runner.execute(Plan(experiments=(experiment,)), Gateway(), options=runner.ExecutionOptions(confirmations=1))[0]

    assert result.assessment.feature == "supported"
    assert result.assessment.parity == "mismatch"
    assert result.assessment.reason == "reproduced across 2 attempts"
    assert len(result.attempts) == 2


def test_missing_provider_credential_is_an_access_result(monkeypatch):
    monkeypatch.delenv("STUB_API_KEY", raising=False)
    experiment = Experiment(
        target=target(),
        case=case(),
        direct_driver_id="http",
        gateway_driver_id="http",
        gateway_surface_id="oai",
        gateway_endpoint="chat/completions",
        transport="buffered",
    )

    result = runner.execute(Plan(experiments=(experiment,)), Gateway())[0]

    assert result.assessment.execution == "access_blocked"
    assert result.assessment.feature == "unknown"
    assert result.assessment.parity == "inconclusive"


def test_gateway_client_failure_is_a_harness_result(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    direct = Observation(outcome="success", text="ok")
    gateway = Observation(outcome="error", error_code="client_exception", error_message="broken decoder")
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver((direct, gateway))})
    experiment = Experiment(
        target=target(),
        case=case(),
        direct_driver_id="sequence",
        gateway_driver_id="sequence",
        gateway_surface_id="oai",
        gateway_endpoint="chat/completions",
        transport="buffered",
    )

    result = runner.execute(Plan(experiments=(experiment,)), Gateway(), options=runner.ExecutionOptions(confirmations=0))[0]

    assert result.assessment.execution == "harness_error"
    assert result.assessment.parity == "inconclusive"


def test_gateway_rate_limit_is_transient():
    gateway = Connection(base_url="http://gateway/inf/v1", api_key="gateway", auth="bearer", headers={}, route="gateway")
    direct = Connection(base_url="http://provider/v1", api_key="provider", auth="bearer", headers={}, route="direct")

    assert status_outcome(gateway, 429) == "transient"
    assert status_outcome(gateway, 500) == "error"
    assert status_outcome(direct, 500) == "transient"


def test_runner_retries_only_the_transient_path(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    direct = Observation(outcome="success", text="ok")
    transient = Observation(outcome="transient", error_code="rate_limit", http_status=429)
    gateway = Observation(outcome="success", text="ok")
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver((direct, transient, gateway))})
    selected = experiment("stub/model", driver_id="sequence")

    result = runner.execute(
        Plan(experiments=(selected,)),
        Gateway(),
        options=runner.ExecutionOptions(confirmations=0, transient_retries=1, retry_backoff_seconds=0),
    )[0]

    assert result.assessment.execution == "completed"
    assert result.assessment.parity == "match"
    assert len(result.attempts) == 2
    assert result.attempts[0].gateway.outcome == "transient"
    assert result.attempts[1].direct == direct
    assert result.attempts[1].gateway == gateway


def test_runner_reports_exhausted_transient_failures_separately(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    direct = Observation(outcome="success", text="ok")
    transient = Observation(outcome="transient", error_code="rate_limit", http_status=429)
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver((direct, transient, transient))})
    selected = experiment("stub/model", driver_id="sequence")

    result = runner.execute(
        Plan(experiments=(selected,)),
        Gateway(),
        options=runner.ExecutionOptions(confirmations=0, transient_retries=1, retry_backoff_seconds=0),
    )[0]

    assert result.assessment.execution == "transient_failure"
    assert result.assessment.parity == "not_evaluated"
    assert len(result.attempts) == 2


def test_runner_uses_independent_provider_and_gateway_endpoints(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    monkeypatch.setattr(runner, "discover", lambda: {"direct": EndpointDriver(), "gateway": EndpointDriver()})
    experiment = Experiment(
        target=target(surface_id="anthropic", endpoint="messages", egress_kind="anthropic"),
        case=case(),
        direct_driver_id="direct",
        gateway_driver_id="gateway",
        gateway_surface_id="oai",
        gateway_endpoint="chat/completions",
        transport="buffered",
    )

    result = runner.execute(Plan(experiments=(experiment,)), Gateway(), options=runner.ExecutionOptions(confirmations=0))[0]

    assert result.direct.client_type == "messages"
    assert result.gateway.client_type == "chat/completions"
    assert result.assessment.parity == "match"


def test_runner_parallelizes_experiments_and_preserves_plan_order(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    driver = ConcurrentDriver()
    monkeypatch.setattr(runner, "discover", lambda: {driver.id: driver})
    plan = Plan(experiments=(experiment("stub/first"), experiment("stub/second")))

    results = runner.execute(plan, Gateway(), options=runner.ExecutionOptions(confirmations=2, concurrency=2))

    assert driver.maximum_active == 2
    assert [result.model_id for result in results] == ["stub/first", "stub/second"]


def test_gateway_authentication_stops_scheduling_new_experiments(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    driver = GatewayAuthDriver()
    monkeypatch.setattr(runner, "discover", lambda: {driver.id: driver})
    plan = Plan(experiments=tuple(experiment(f"stub/{index}", driver.id) for index in range(4)))

    results = runner.execute(plan, Gateway(), options=runner.ExecutionOptions(confirmations=0, concurrency=2))

    assert driver.direct_calls == 2
    assert [result.model_id for result in results] == [f"stub/{index}" for index in range(4)]
    assert all(result.assessment.execution == "access_blocked" for result in results)
    assert all(len(result.attempts) == 1 for result in results)
