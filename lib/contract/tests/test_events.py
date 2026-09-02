from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from contract import UsageEvent, uuid7

USAGE_EVENT_ADAPTER = TypeAdapter(UsageEvent)


def usage_event(**overrides: object) -> dict[str, object]:
    credential_id = uuid7()
    return {
        "event_id": uuid7(),
        "request_id": uuid7(),
        "occurred_at": datetime.now(tz=UTC),
        "org_id": uuid7(),
        "workspace_id": uuid7(),
        "key_id": "external-key",
        "model_id": "model",
        "provider_id": "provider",
        "bundle_id": uuid7(),
        "input_tokens": 1,
        "output_tokens": 1,
        "cost_usd": 0,
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
        USAGE_EVENT_ADAPTER.validate_python(usage_event(status="denied", provider_id="provider"))
    with pytest.raises(ValidationError):
        USAGE_EVENT_ADAPTER.validate_python(usage_event(status="denied", provider_id="", credential_id=uuid7(), credential_scope="workspace"))


def test_usage_events_accept_opaque_key_ids():
    event = USAGE_EVENT_ADAPTER.validate_python(usage_event())
    assert event.key_id == "external-key"
