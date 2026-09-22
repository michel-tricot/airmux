from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from contract import GatewayRequestFinishedV1, IngestEvent, UsageEvent, uuid7

USAGE_EVENT_ADAPTER = TypeAdapter(UsageEvent)
INGEST_EVENT_ADAPTER = TypeAdapter(IngestEvent)


def usage_event(**overrides: object) -> dict[str, object]:
    credential_id = uuid7()
    request_started_at = datetime(2026, 9, 22, 12, tzinfo=UTC)
    attempt_started_at = datetime(2026, 9, 22, 12, 0, 1, tzinfo=UTC)
    return {
        "event_type": "usage",
        "event_id": uuid7(),
        "request_id": uuid7(),
        "request_started_at": request_started_at,
        "attempt_started_at": attempt_started_at,
        "occurred_at": datetime(2026, 9, 22, 12, 0, 2, tzinfo=UTC),
        "org_id": uuid7(),
        "workspace_id": uuid7(),
        "key_id": "external-key",
        "authentication_source": "inference_key",
        "authentication_label": "Production key",
        "model_id": "model",
        "user_id": uuid7(),
        "principal_label": "Checkout service",
        "principal_type": "service_account",
        "workspace_label": "Production",
        "requested_model_id": "model",
        "requested_capabilities": [],
        "provider_id": "provider",
        "bundle_id": uuid7(),
        "input_tokens": 1,
        "output_tokens": 1,
        "token_usage_source": "provider",
        "attempt_index": 1,
        "max_output_tokens": 128,
        "input_price_per_mtok": "1",
        "output_price_per_mtok": "2",
        "cache_read_price_per_mtok": "0.1",
        "cache_write_price_per_mtok": "1.25",
        "cost_source": "catalog_estimate",
        "cost_usd": "0",
        "cost_input_usd": "0",
        "cost_output_usd": "0",
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "latency_ms": 1,
        "status": "ok",
        "stream": False,
        "credential_id": credential_id,
        "credential_scope": "workspace",
        "credential_name": "default",
        **overrides,
    }


def finished_request(**overrides: object) -> dict[str, object]:
    request_started_at = datetime(2026, 9, 22, 12, tzinfo=UTC)
    return {
        "event_type": "gateway_request_finished",
        "schema_version": 1,
        "event_id": uuid7(),
        "request_id": uuid7(),
        "request_started_at": request_started_at,
        "occurred_at": datetime(2026, 9, 22, 12, 0, 2, tzinfo=UTC),
        "org_id": uuid7(),
        "workspace_id": uuid7(),
        "key_id": "external-key",
        "authentication_source": "inference_key",
        "authentication_label": "Production key",
        "user_id": uuid7(),
        "principal_label": "Checkout service",
        "principal_type": "service_account",
        "workspace_label": "Production",
        "requested_model_id": "model",
        "requested_capabilities": [],
        "bundle_id": uuid7(),
        "stream": False,
        "outcome": "succeeded",
        "expected_attempts": 2,
        "latency_ms": 2000,
        **overrides,
    }


def test_ingest_event_distinguishes_terminal_request_observations():
    event = INGEST_EVENT_ADAPTER.validate_python(finished_request())

    assert isinstance(event, GatewayRequestFinishedV1)
    assert event.expected_attempts == 2
    assert event.outcome == "succeeded"


@pytest.mark.parametrize("field", ["event_id", "request_started_at", "outcome", "expected_attempts", "latency_ms"])
def test_terminal_request_observation_requires_every_fact(field):
    payload = finished_request()
    del payload[field]

    with pytest.raises(ValidationError):
        INGEST_EVENT_ADAPTER.validate_python(payload)


def test_terminal_request_observation_rejects_unordered_time_and_negative_attempts():
    with pytest.raises(ValidationError):
        GatewayRequestFinishedV1.model_validate(finished_request(expected_attempts=-1))
    with pytest.raises(ValidationError):
        GatewayRequestFinishedV1.model_validate(
            finished_request(
                request_started_at=datetime(2026, 9, 22, 12, 0, 3, tzinfo=UTC),
                occurred_at=datetime(2026, 9, 22, 12, 0, 2, tzinfo=UTC),
            )
        )
    with pytest.raises(ValidationError, match="at least one routed attempt"):
        GatewayRequestFinishedV1.model_validate(finished_request(outcome="succeeded", expected_attempts=0))


def test_unavailable_attempt_requires_unknown_tokens_and_cost_but_keeps_rates():
    event = USAGE_EVENT_ADAPTER.validate_python(
        usage_event(
            token_usage_source="unavailable",
            input_tokens=None,
            output_tokens=None,
            cache_read_tokens=None,
            cache_write_tokens=None,
            cost_source="unavailable",
            cost_usd=None,
            cost_input_usd=None,
            cost_output_usd=None,
            status="timeout",
        )
    )

    assert event.token_usage_source == "unavailable"
    assert event.input_tokens is None
    assert event.input_price_per_mtok == 1


def test_partial_attempt_requires_known_counts_and_catalog_cost():
    event = USAGE_EVENT_ADAPTER.validate_python(usage_event(token_usage_source="partial", status="cancelled"))

    assert event.token_usage_source == "partial"
    assert event.cost_source == "catalog_estimate"


def test_usage_rejects_cache_counts_larger_than_total_input():
    with pytest.raises(ValidationError, match="cache"):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(input_tokens=5, cache_read_tokens=4, cache_write_tokens=2))


def test_routed_usage_requires_a_complete_credential_reference():
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(credential_scope=None))
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(credential_id=None))


def test_early_denial_rejects_provider_and_credential_data():
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(status="denied", provider_id="provider"))
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(status="denied", provider_id="", credential_id=uuid7(), credential_scope="workspace"))


def test_usage_events_accept_opaque_key_ids():
    event = USAGE_EVENT_ADAPTER.validate_python(usage_event())
    assert event.key_id == "external-key"


def test_routed_usage_requires_ordered_immutable_execution_evidence():
    event = USAGE_EVENT_ADAPTER.validate_python(usage_event())

    assert event.attempt_index == 1
    assert event.request_started_at < event.attempt_started_at < event.occurred_at
    assert event.authentication_source == "inference_key"
    assert event.authentication_label == "Production key"
    assert event.principal_label == "Checkout service"
    assert event.principal_type == "service_account"
    assert event.workspace_label == "Production"
    assert event.credential_name == "default"
    assert event.cost_source == "catalog_estimate"
    assert event.input_price_per_mtok == 1


@pytest.mark.parametrize("field", ["attempt_index", "attempt_started_at", "credential_name", "input_price_per_mtok", "cost_source"])
def test_routed_usage_rejects_missing_attempt_evidence(field):
    payload = usage_event()
    del payload[field]
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authentication_label", ""),
        ("authentication_label", "a" * 201),
        ("principal_label", ""),
        ("principal_label", "p" * 321),
        ("workspace_label", ""),
        ("workspace_label", "w" * 201),
        ("credential_name", ""),
        ("credential_name", "c" * 81),
    ],
)
def test_usage_execution_labels_are_bounded(field, value):
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(**{field: value}))


def test_routed_usage_rejects_nonpositive_attempt_order():
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(attempt_index=0))


@pytest.mark.parametrize(
    ("authentication_source", "principal_type"),
    [("local", "human"), ("local", "service_account"), ("inference_key", "local"), ("playground", "local")],
)
def test_usage_principal_kind_matches_authentication_source(authentication_source, principal_type):
    with pytest.raises(ValidationError, match="principal_type must match"):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(authentication_source=authentication_source, principal_type=principal_type))


@pytest.mark.parametrize(
    ("request_started_at", "attempt_started_at", "occurred_at"),
    [
        (
            datetime(2026, 9, 22, 12, 0, 2, tzinfo=UTC),
            datetime(2026, 9, 22, 12, 0, 1, tzinfo=UTC),
            datetime(2026, 9, 22, 12, 0, 3, tzinfo=UTC),
        ),
        (
            datetime(2026, 9, 22, 12, tzinfo=UTC),
            datetime(2026, 9, 22, 12, 0, 3, tzinfo=UTC),
            datetime(2026, 9, 22, 12, 0, 2, tzinfo=UTC),
        ),
    ],
)
def test_routed_usage_rejects_unordered_timestamps(request_started_at, attempt_started_at, occurred_at):
    with pytest.raises(ValidationError, match="timestamps must be ordered"):
        USAGE_EVENT_ADAPTER.validate_python(
            usage_event(
                request_started_at=request_started_at,
                attempt_started_at=attempt_started_at,
                occurred_at=occurred_at,
            )
        )


def test_usage_event_cost_must_equal_its_exact_components() -> None:
    with pytest.raises(ValidationError, match="cost_usd must equal"):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(cost_usd="0.3", cost_input_usd="0.1", cost_output_usd="0.200000000001"))


def test_denied_usage_event_cost_must_be_zero() -> None:
    with pytest.raises(ValidationError, match="denied events must have zero cost"):
        USAGE_EVENT_ADAPTER.validate_python(
            usage_event(
                status="denied",
                provider_id="",
                credential_id=None,
                credential_scope=None,
                input_tokens=0,
                output_tokens=0,
                token_usage_source="not_applicable",
                attempt_started_at=None,
                attempt_index=None,
                input_price_per_mtok=None,
                output_price_per_mtok=None,
                cache_read_price_per_mtok=None,
                cache_write_price_per_mtok=None,
                cost_source="not_applicable",
                credential_name=None,
                cost_usd="0.1",
                cost_input_usd="0.1",
            )
        )


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
                credential_name=None,
                attempt_index=None,
                attempt_started_at=None,
                input_price_per_mtok=None,
                output_price_per_mtok=None,
                cache_read_price_per_mtok=None,
                cache_write_price_per_mtok=None,
                cost_source="not_applicable",
                token_usage_source=source,
            )
        )


def test_denied_usage_rejects_attempt_and_pricing_evidence():
    denied = usage_event(
        status="denied",
        provider_id="",
        credential_id=None,
        credential_scope=None,
        credential_name=None,
        attempt_index=None,
        attempt_started_at=None,
        input_price_per_mtok=None,
        output_price_per_mtok=None,
        cache_read_price_per_mtok=None,
        cache_write_price_per_mtok=None,
        cost_source="not_applicable",
        token_usage_source="not_applicable",
        input_tokens=0,
        output_tokens=0,
        cost_usd="0",
        cost_input_usd="0",
    )

    assert USAGE_EVENT_ADAPTER.validate_python(denied).attempt_index is None
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python({**denied, "attempt_index": 1})
