from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from gateway_harness import DIALECTS, FAMILIES, error_of, stream_payloads, streamed_text, text_of
from upstream import TEXT, UPSTREAM_KEY, Reply

if TYPE_CHECKING:
    from gateway_harness import Dialect, Gateway
    from upstream import Family


def fallback(gateway: Gateway, *, attempts: int = 2, timeout_ms: int = 10000) -> None:
    gateway.add_policy(
        [
            {
                "kind": "fallback",
                "models": ["model-c", "model-d"],
                "on": ["rate_limited", "upstream_unavailable", "timeout"],
                "max_attempts": attempts,
                "timeout_ms": timeout_ms,
            }
        ]
    )


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
@pytest.mark.parametrize(
    "provider_failure", [(401, "credential_rejected"), (429, "rate_limited"), (503, "upstream_error")], ids=["401", "429", "503"]
)
def test_provider_errors_keep_the_caller_shape_and_record_a_valid_event(
    gateway: Gateway, dialect: Dialect, family: Family, stream: bool, provider_failure: tuple[int, str]
):
    status, event_status = provider_failure
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(status=status)
    gateway.start()
    response = gateway.request(dialect, stream=stream)
    assert response.status_code == status, response.text
    assert error_of(dialect, response) == "provider_failure"
    assert UPSTREAM_KEY not in response.text
    (event,) = gateway.events(1)
    assert (event.status, event.model_id, event.provider_id, event.stream) == (event_status, "model-a", "stub", stream)
    assert event.input_tokens > 0
    assert event.output_tokens == 0


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_malformed_provider_success_is_an_error_and_service_recovers(gateway: Gateway, dialect: Dialect, family: Family, stream: bool):
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(malformed="event" if stream else "json")
    gateway.start()
    response = gateway.request(dialect, stream=stream)
    if stream:
        assert response.status_code == 200
        errors = [event.get("error", event) for event in stream_payloads(response) if "error" in event or event.get("type") == "error"]
        assert len(errors) == 1
        assert errors[0]["type" if dialect == "anthropic" else "code"] == "invalid_upstream_response"
    else:
        assert response.status_code == 502
        assert error_of(dialect, response) == "invalid_upstream_response"
    provider.replies["upstream-model-a"] = Reply()
    assert gateway.request(dialect).status_code == 200
    assert [event.status for event in gateway.events(2)] == ["upstream_error", "ok"]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_truncated_stream_reports_failure_without_switching_to_a_backup(gateway: Gateway, dialect: Dialect, family: Family):
    provider = gateway.add_provider(family)
    backup = gateway.add_provider(name="backup", models=("model-c", "model-d"))
    provider.replies["upstream-model-a"] = Reply(terminal=False)
    fallback(gateway)
    gateway.start()
    response = gateway.request(dialect, stream=True)
    assert response.status_code == 200
    assert streamed_text(dialect, response) == TEXT
    assert "invalid_upstream_response" in response.text
    assert backup.requests == []
    (event,) = gateway.events(1)
    assert event.status == "upstream_error"
    if family == "openai_responses":
        assert event.input_tokens > 0
        assert event.output_tokens > 0
        assert event.cache_read_tokens == 0
    else:
        assert (event.input_tokens, event.output_tokens) == (11, 3)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
@pytest.mark.parametrize("status", [429, 503])
def test_fallback_crosses_provider_families_and_preserves_attempt_accounting(
    gateway: Gateway, dialect: Dialect, family: Family, stream: bool, status: int
):
    provider = gateway.add_provider(family)
    backup_family: Family = "anthropic" if family != "anthropic" else "openai_responses"
    backup = gateway.add_provider(backup_family, name="backup", models=("model-c", "model-d"))
    provider.replies["upstream-model-a"] = Reply(status=status)
    fallback(gateway)
    gateway.start()
    response = gateway.request(dialect, stream=stream)
    assert response.status_code == 200, response.text
    assert (streamed_text(dialect, response) if stream else text_of(dialect, response)) == TEXT
    assert [request.body["model"] for request in provider.requests] == ["upstream-model-a"]
    assert [request.body["model"] for request in backup.requests] == ["upstream-model-c"]
    first, second = gateway.events(2)
    assert first.request_id == second.request_id
    assert first.bundle_id == second.bundle_id
    assert first.status == ("rate_limited" if status == 429 else "upstream_error")
    assert (second.status, second.model_id, second.provider_id) == ("ok", "model-c", "backup")
    assert first.credential_id != second.credential_id


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("restriction", ["model", "provider", "price"])
def test_fallback_cannot_bypass_a_restriction_matched_on_the_original_request(gateway: Gateway, dialect: Dialect, restriction: str):
    provider = gateway.add_provider()
    backup = gateway.add_provider(name="backup", models=("model-c", "model-d"))
    provider.replies["upstream-model-a"] = Reply(status=503)
    fallback(gateway)
    action: dict[str, object]
    if restriction == "model":
        action = {"kind": "models", "names": ["model-a"]}
    elif restriction == "provider":
        action = {"kind": "providers", "names": ["stub"]}
    else:
        gateway.taxonomy["models"][2]["input_price_per_mtok"] = 10
        gateway.taxonomy["models"][3]["input_price_per_mtok"] = 10
        action = {"kind": "price_limit", "max_input_price_per_mtok": "2", "max_output_price_per_mtok": "5"}
    gateway.add_policy([action], match={"kind": "request", "models": ["model-a"]}, priority=200)
    gateway.start()
    response = gateway.request(dialect)
    assert response.status_code == 503
    assert len(provider.requests) == 1
    assert backup.requests == []
    assert gateway.events(1)[0].status == "upstream_error"


@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_fallback_stops_at_the_attempt_limit(gateway: Gateway, stream: bool):
    provider = gateway.add_provider()
    backup = gateway.add_provider(name="backup", models=("model-c", "model-d"))
    provider.replies["upstream-model-a"] = Reply(status=503)
    backup.replies["upstream-model-c"] = Reply(status=503)
    fallback(gateway, attempts=2)
    gateway.start()
    assert gateway.request(stream=stream).status_code == 503
    assert [request.body["model"] for request in backup.requests] == ["upstream-model-c"]
    first, second = gateway.events(2)
    assert first.request_id == second.request_id
    assert first.status == second.status == "upstream_error"


def test_fallback_deadline_cancels_the_active_attempt_and_gateway_recovers(gateway: Gateway):
    provider = gateway.add_provider()
    backup = gateway.add_provider(name="backup", models=("model-c", "model-d"))
    provider.replies["upstream-model-a"] = Reply(delay_s=0.5)
    fallback(gateway, timeout_ms=100)
    gateway.start()
    response = gateway.request()
    assert response.status_code == 504
    assert error_of("canonical", response) == "fallback_deadline_exceeded"
    assert backup.requests == []
    assert gateway.events(1)[0].status == "cancelled"
    provider.replies["upstream-model-a"] = Reply()
    assert gateway.request().status_code == 200
    assert [event.status for event in gateway.events(2)] == ["cancelled", "ok"]
