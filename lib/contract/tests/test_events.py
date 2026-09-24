from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError

from contract import RoutedUsageEventV1, UsageEvent, uuid7

USAGE_EVENT_ADAPTER = TypeAdapter(UsageEvent)


def usage_event(**overrides: object) -> dict[str, object]:
    credential_id = uuid7()
    return {
        "event_id": uuid7(),
        "request_id": uuid7(),
        "request_started_at": datetime.now(tz=UTC),
        "attempt_started_at": datetime.now(tz=UTC),
        "occurred_at": datetime.now(tz=UTC),
        "org_id": uuid7(),
        "workspace_id": uuid7(),
        "key_id": "external-key",
        "request_source": "inference_key",
        "model_id": "model",
        "user_id": uuid7(),
        "requested_model_id": "model",
        "requested_capabilities": [],
        "provider_id": "provider",
        "bundle_id": uuid7(),
        "input_tokens": 1,
        "output_tokens": 1,
        "token_usage_source": "provider",
        "max_output_tokens": 128,
        "cost_usd": "0",
        "latency_ms": 1,
        "status": "ok",
        "stream": False,
        "credential_id": credential_id,
        "credential_scope": "workspace",
        **overrides,
    }


def test_routed_usage_requires_a_complete_credential_reference():
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(credential_scope=None))
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(credential_id=None))


def test_early_denial_rejects_provider_and_credential_data():
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(status="denied", provider_id="provider", attempt_started_at=None))
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(
            usage_event(status="denied", provider_id="", credential_id=uuid7(), credential_scope="workspace", attempt_started_at=None)
        )


def test_usage_events_accept_opaque_key_ids():
    event = USAGE_EVENT_ADAPTER.validate_python(usage_event())
    assert event.key_id == "external-key"


def test_routed_usage_latency_is_described_as_attempt_latency():
    description = RoutedUsageEventV1.model_json_schema()["properties"]["latency_ms"]["description"]
    assert description == "Gateway latency in milliseconds: per attempt when routed, end-to-end for a denial before routing"


@pytest.mark.parametrize("source", ["inference_key", "playground"])
def test_request_source_survives_event_serialization(source):
    event = USAGE_EVENT_ADAPTER.validate_python(usage_event(request_source=source))
    assert USAGE_EVENT_ADAPTER.validate_json(event.model_dump_json()).request_source == source


@pytest.mark.parametrize("source", [None, "unknown"])
def test_request_source_rejects_unknown_values(source):
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(request_source=source))


def test_usage_event_keeps_observed_cost_even_when_components_do_not_match() -> None:
    event = USAGE_EVENT_ADAPTER.validate_python(usage_event(cost_usd="0.3", cost_input_usd="0.1", cost_output_usd="0.200000000001"))
    assert event.cost_usd == Decimal("0.3")


def test_denied_usage_event_keeps_the_observed_cost() -> None:
    event = USAGE_EVENT_ADAPTER.validate_python(
        usage_event(
            status="denied",
            provider_id="",
            credential_id=None,
            credential_scope=None,
            attempt_started_at=None,
            input_tokens=0,
            output_tokens=0,
            token_usage_source="not_applicable",
            cost_usd="0.1",
            cost_input_usd="0.1",
        )
    )
    assert event.cost_usd == Decimal("0.1")


@pytest.mark.parametrize("source", ["provider", "estimated"])
def test_token_usage_source_survives_event_serialization(source):
    event = USAGE_EVENT_ADAPTER.validate_python(usage_event(token_usage_source=source))
    assert USAGE_EVENT_ADAPTER.validate_json(event.model_dump_json()).token_usage_source == source


@pytest.mark.parametrize("source", [None, "unknown", "not_applicable"])
def test_routed_usage_rejects_invalid_token_sources(source):
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(token_usage_source=source))


def test_token_usage_source_is_required():
    event = usage_event()
    del event["token_usage_source"]
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(event)


@pytest.mark.parametrize("source", ["provider", "estimated"])
def test_denied_usage_rejects_routed_token_sources(source):
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(
            usage_event(
                status="denied",
                provider_id="",
                credential_id=None,
                credential_scope=None,
                token_usage_source=source,
                attempt_started_at=None,
            )
        )
