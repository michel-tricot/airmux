from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING

from rich.console import Console

from provider_parity import runner
from provider_parity.compare import compare
from provider_parity.diagnostics import case_result
from provider_parity.drivers.base import Connection, SDKDriver
from provider_parity.models import Case, Experiment, Observation, Oracle, PairResult, Plan, Request, Target
from provider_parity.progress import ConsoleProgress

if TYPE_CHECKING:
    from provider_parity.models import Transport


class Gateway:
    def require_ready(self) -> None:
        return

    def connection(self, endpoint: str) -> Connection:
        return Connection(base_url="http://gateway.example/inf/v1", api_key="gateway-key", auth="bearer", headers={}, route="gateway")


class ThrowingDriver(SDKDriver):
    id = "throwing"
    endpoints = frozenset({"responses"})

    def execute(self, connection: Connection, endpoint: str, model: str, case: Case, transport: Transport) -> Observation:
        if connection.route == "gateway" and case.id == "text.protocol-error":
            message = "vendor SDK could not parse the gateway response"
            raise RuntimeError(message)
        return Observation(outcome="success", text="ok", sdk_type="StubResponse")


def test_sdk_exception_is_reported_as_parity_evidence_and_the_run_continues(monkeypatch):
    monkeypatch.setenv("STUB_API_KEY", "provider-key")
    monkeypatch.setattr(runner, "discover", lambda: {"throwing": ThrowingDriver()})
    target = Target(
        provider_id="stub",
        surface_id="stub_responses",
        endpoint="responses",
        egress_kind="openai_responses",
        base_url="http://provider.example/v1",
        credential_env="STUB_API_KEY",
        auth="bearer",
        headers={},
        model_id="stub/model",
        upstream_model="upstream-model",
        context_window=8192,
        max_output_tokens=1024,
        input_modalities=frozenset({"text"}),
        capabilities=frozenset(),
        parameter_support={},
    )
    failed_case = Case(
        id="text.protocol-error",
        title="Protocol error",
        request=Request(messages=({"role": "user", "content": "Reply with ok"},)),
        oracle=Oracle(text_contains="ok"),
    )
    passing_case = failed_case.model_copy(update={"id": "text.after-error", "title": "After error"})
    plan = Plan(
        experiments=(
            Experiment(target=target, case=failed_case, driver_id="throwing", transport="buffered"),
            Experiment(target=target, case=passing_case, driver_id="throwing", transport="buffered"),
        )
    )

    progress = []
    failed, passing = runner.execute(plan, Gateway(), progress=progress.append)

    assert failed.direct.outcome == "success"
    assert failed.gateway.outcome == "error"
    assert failed.gateway.error_code == "sdk_exception"
    assert failed.gateway.sdk_type == "RuntimeError"
    assert failed.comparison.verdict == "gateway_regression"
    assert passing.comparison.verdict == "parity"
    assert [(event.kind, event.path) for event in progress] == [
        ("experiment_started", None),
        ("path_started", "direct"),
        ("path_completed", "direct"),
        ("path_started", "gateway"),
        ("path_completed", "gateway"),
        ("experiment_completed", None),
        ("experiment_started", None),
        ("path_started", "direct"),
        ("path_completed", "direct"),
        ("path_started", "gateway"),
        ("path_completed", "gateway"),
        ("experiment_completed", None),
    ]
    assert progress[0].index == 1
    assert progress[0].total == 2
    assert progress[4].observation == failed.gateway
    assert progress[-1].result == passing

    output = StringIO()
    console_progress = ConsoleProgress(Console(file=output, force_terminal=False, color_system=None))
    console_progress.start(plan, "http://gateway.example")
    for event in progress[:6]:
        console_progress(event)
    rendered = output.getvalue()
    assert "Provider parity | 2 experiments | 4 requests | http://gateway.example" in rendered
    assert "[1/2] stub/model" in rendered
    assert "text.protocol-error | buffered via throwing" in rendered
    assert "✓ SUCCESS Direct" in rendered
    assert "✗ ERROR Gateway" in rendered
    assert "sdk_exception | RuntimeError" in rendered
    assert "✗ GATEWAY REGRESSION" in rendered
    assert "direct satisfied the oracle and gateway did not" in rendered
    assert "Outcome: direct=success | gateway=error" in rendered
    assert "Case oracle: direct=satisfied | gateway=not satisfied" in rendered
    assert 'Direct: success; text="ok"' in rendered
    assert 'Gateway: error; text=""' in rendered

    observation = Observation(outcome="success", finish_reason="length", usage_present=True, reasoning_present=True)
    oracle = Oracle(text_nonempty=True)
    matched_failure = PairResult(
        case_id="text.basic",
        provider_id="stub",
        surface_id="stub_responses",
        model_id="stub/model",
        sdk="throwing",
        transport="buffered",
        direct=observation,
        gateway=observation,
        comparison=compare(observation, observation, oracle),
    )
    experiment = plan.experiments[1].model_copy(update={"case": plan.experiments[1].case.model_copy(update={"oracle": oracle})})
    matched_output = StringIO()
    matched_progress = ConsoleProgress(Console(file=matched_output, force_terminal=False, color_system=None))
    matched_progress(runner.ProgressEvent(kind="experiment_completed", index=1, total=1, experiment=experiment, result=matched_failure))
    rendered_match = matched_output.getvalue()
    assert "✓ PARITY" in rendered_match
    assert "! CASE FAILED" in rendered_match
    assert "expected non-empty assistant text" in rendered_match
    assert case_result(matched_failure.comparison) == "failed both"
