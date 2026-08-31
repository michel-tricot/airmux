from __future__ import annotations

import threading

from model_audit import runner
from model_audit.drivers.base import ClientDriver, Connection, status_outcome
from model_audit.models import Experiment, Failure, Observation, Plan
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


class ProviderBillingDriver(ClientDriver):
    id = "provider-billing"
    mode = "api"
    endpoints = frozenset({"chat/completions"})

    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, connection, endpoint, model, case, transport):
        self.calls.append(model)
        if model.startswith("billed/"):
            return Observation(outcome="inconclusive", error_code="provider_billing_access", http_status=429)
        return Observation(outcome="success", text="ok")


class DirectAuthDriver(ClientDriver):
    id = "direct-auth"
    mode = "api"
    endpoints = frozenset({"chat/completions", "responses"})

    def __init__(self) -> None:
        self.direct_calls = 0

    def execute(self, connection, endpoint, model, case, transport):
        if connection.route == "direct":
            self.direct_calls += 1
            return Observation(outcome="inconclusive", error_code="direct_authentication", http_status=401)
        return Observation(outcome="success", text="ok")


def experiment(model_id: str, driver_id: str = "concurrent", provider_id: str = "stub") -> Experiment:
    return Experiment(
        target=target(provider_id=provider_id, model_id=model_id, upstream_model=model_id),
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


def test_runner_reports_a_majority_verdict_as_flaky(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    failed = Observation(outcome="success", text="wrong")
    passed = Observation(outcome="success", text="ok")
    observations = (failed, passed, passed, passed, passed, passed)
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver(observations)})
    selected = experiment("stub/model", driver_id="sequence")

    result = runner.execute(Plan(experiments=(selected,)), Gateway(), options=runner.ExecutionOptions(confirmations=2))[0]

    assert result.assessment.feature == "supported"
    assert result.assessment.parity == "match"
    assert result.assessment.stability == "flaky"
    assert result.assessment.reason == "behavior varied across 3 attempts; 2 agreed on match"
    assert result.direct == passed
    assert result.gateway == passed


def test_runner_reports_a_tied_classification_as_flaky_not_evaluated(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    failed = Observation(outcome="success", text="wrong")
    passed = Observation(outcome="success", text="ok")
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver((failed, passed, passed, passed))})
    selected = experiment("stub/model", driver_id="sequence")

    result = runner.execute(Plan(experiments=(selected,)), Gateway(), options=runner.ExecutionOptions(confirmations=1))[0]

    assert result.assessment.feature == "unknown"
    assert result.assessment.parity == "not_evaluated"
    assert result.assessment.stability == "flaky"
    assert result.assessment.reason == "behavior varied across 2 attempts with no majority"
    assert result.assessment.variance == "provider"


def test_runner_attributes_direct_control_variation_to_the_provider(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    passed = Observation(outcome="success", text="ok")
    failed = Observation(outcome="success", text="wrong")
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver((failed, passed, passed, passed))})
    selected = experiment("stub/model", driver_id="sequence")

    result = runner.execute(Plan(experiments=(selected,)), Gateway(), options=runner.ExecutionOptions(confirmations=1))[0]

    assert result.assessment.stability == "flaky"
    assert result.assessment.variance == "provider"
    assert result.assessment.parity == "not_evaluated"


def test_runner_attributes_gateway_control_variation_to_the_gateway(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    passed = Observation(outcome="success", text="ok")
    failed = Observation(outcome="success", text="wrong")
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver((passed, failed, passed, passed))})
    selected = experiment("stub/model", driver_id="sequence")

    result = runner.execute(Plan(experiments=(selected,)), Gateway(), options=runner.ExecutionOptions(confirmations=1))[0]

    assert result.assessment.stability == "flaky"
    assert result.assessment.variance == "gateway"
    assert result.assessment.parity == "not_evaluated"


def test_runner_confirms_a_mismatch_when_only_the_details_vary(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    direct = Observation(outcome="success", text="ok")
    gateway_without_text = Observation(outcome="success", text="wrong")
    gateway_error = Observation(outcome="error", error_code="http_protocol_error")
    observations = (direct, gateway_without_text, direct, gateway_error)
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver(observations)})
    selected = experiment("stub/model", driver_id="sequence")

    result = runner.execute(Plan(experiments=(selected,)), Gateway(), options=runner.ExecutionOptions(confirmations=1))[0]

    assert result.assessment.execution == "completed"
    assert result.assessment.feature == "supported"
    assert result.assessment.parity == "mismatch"
    assert result.assessment.stability == "stable"
    assert result.assessment.reason == "reproduced across 2 attempts"


def test_runner_keeps_stable_parity_when_feature_support_varies(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    passed = Observation(outcome="success", text="ok")
    failed = Observation(outcome="success", text="wrong")
    observations = (passed, failed, failed, passed)
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver(observations)})
    selected = experiment("stub/model", driver_id="sequence")

    result = runner.execute(Plan(experiments=(selected,)), Gateway(), options=runner.ExecutionOptions(confirmations=1))[0]

    assert result.assessment.execution == "completed"
    assert result.assessment.feature == "unknown"
    assert result.assessment.parity == "mismatch"
    assert result.assessment.stability == "flaky"
    assert result.assessment.difference_codes == ("oracle",)


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


def test_runner_retries_a_retryable_gateway_error_then_reports_the_persistent_gap(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    direct = Observation(outcome="success", text="ok")
    gateway = Observation(
        outcome="error",
        error_code="gateway_internal",
        http_status=500,
        failure=Failure(kind="gateway", origin="gateway", retryable=True, code="gateway_internal", http_status=500),
    )
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver((direct, gateway, gateway))})
    selected = experiment("stub/model", driver_id="sequence")

    result = runner.execute(
        Plan(experiments=(selected,)),
        Gateway(),
        options=runner.ExecutionOptions(confirmations=0, transient_retries=1, retry_backoff_seconds=0),
    )[0]

    assert len(result.attempts) == 2
    assert result.assessment.execution == "completed"
    assert result.assessment.parity == "mismatch"


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


def test_provider_billing_failure_stops_only_that_provider(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    driver = ProviderBillingDriver()
    monkeypatch.setattr(runner, "discover", lambda: {driver.id: driver})
    plan = Plan(
        experiments=(
            experiment("billed/first", driver.id, provider_id="billed"),
            experiment("billed/second", driver.id, provider_id="billed"),
            experiment("healthy/first", driver.id, provider_id="healthy"),
        )
    )

    results = runner.execute(plan, Gateway(), options=runner.ExecutionOptions(confirmations=0, concurrency=1))

    assert driver.calls == ["billed/first", "billed/first", "healthy/first", "healthy/first"]
    assert [result.assessment.execution for result in results] == ["access_blocked", "access_blocked", "completed"]


def test_direct_access_block_is_shared_across_gateway_surfaces(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    driver = DirectAuthDriver()
    monkeypatch.setattr(runner, "discover", lambda: {driver.id: driver})
    first = experiment("stub/model", driver.id)
    second = first.model_copy(update={"gateway_surface_id": "oai_responses", "gateway_endpoint": "responses"})

    results = runner.execute(Plan(experiments=(first, second)), Gateway(), options=runner.ExecutionOptions(confirmations=0, concurrency=1))

    assert driver.direct_calls == 1
    assert all(result.assessment.execution == "access_blocked" for result in results)
