from __future__ import annotations

from model_audit import runner
from model_audit.drivers.base import ClientDriver, Connection
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


def test_runner_confirms_and_reports_a_gateway_gap(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    direct = Observation(outcome="success", text="ok")
    gateway = Observation(outcome="rejected", http_status=400, error_code="invalid_request_error", error_message="bad request")
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver((direct, gateway, direct, gateway))})
    experiment = Experiment(target=target(), case=case(), driver_id="sequence", transport="buffered")

    result = runner.execute(Plan(experiments=(experiment,)), Gateway(), options=runner.ExecutionOptions(confirmations=1))[0]

    assert result.assessment.feature == "supported"
    assert result.assessment.parity == "mismatch"
    assert result.assessment.reason == "reproduced across 2 attempts"
    assert len(result.confirmations) == 1


def test_missing_provider_credential_is_an_access_result(monkeypatch):
    monkeypatch.delenv("STUB_API_KEY", raising=False)
    experiment = Experiment(target=target(), case=case(), driver_id="http", transport="buffered")

    result = runner.execute(Plan(experiments=(experiment,)), Gateway())[0]

    assert result.assessment.execution == "access_blocked"
    assert result.assessment.feature == "unknown"
    assert result.assessment.parity == "inconclusive"


def test_gateway_client_failure_is_a_harness_result(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider")
    direct = Observation(outcome="success", text="ok")
    gateway = Observation(outcome="error", error_code="client_exception", error_message="broken decoder")
    monkeypatch.setattr(runner, "discover", lambda: {"sequence": SequenceDriver((direct, gateway))})
    experiment = Experiment(target=target(), case=case(), driver_id="sequence", transport="buffered")

    result = runner.execute(Plan(experiments=(experiment,)), Gateway(), options=runner.ExecutionOptions(confirmations=0))[0]

    assert result.assessment.execution == "harness_error"
    assert result.assessment.parity == "inconclusive"
