from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from gateway_harness import DIALECTS, PROTOCOLS, error_of, request_body, text_of
from upstream import TEXT

if TYPE_CHECKING:
    from gateway_harness import Dialect, Gateway


def test_ready_gateway_completes_and_records_usage(gateway: Gateway):
    provider = gateway.add_provider()
    gateway.start()
    assert httpx.get(f"{gateway.url}/healthz").json() == {"status": "ok"}
    assert httpx.get(f"{gateway.url}/readyz").json() == {"status": "ready"}
    response = gateway.request()
    assert response.status_code == 200, response.text
    assert text_of("openai_chat_completions", response) == TEXT
    metrics = httpx.get(f"{gateway.url}/metrics")
    assert metrics.status_code == 200
    assert "airmux_data_plane_http_requests_total" in metrics.text
    assert 'route="/inf/v1/chat/completions"' in metrics.text
    assert provider.requests[0].body["model"] == "upstream-model-a"
    (event,) = gateway.events(1)
    assert (event.status, event.model_id, event.provider_id, event.key_id, event.stream) == ("ok", "model-a", "stub", "local-0", False)
    assert event.request_source == "inference_key"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("key", [None, "sk-inf-wrong"])
def test_authentication_rejects_requests_before_spending_provider_credentials(gateway: Gateway, dialect: Dialect, key: str | None):
    provider = gateway.add_provider()
    gateway.start()
    response = httpx.post(
        gateway.url + PROTOCOLS["ingress"][dialect],
        headers=gateway.headers(dialect, key) if key is not None else {},
        json=request_body(dialect),
    )
    assert response.status_code == 401
    expected = "missing_bearer_token" if key is None else "invalid_token"
    assert error_of("openai_chat_completions" if dialect == "openai_chat_completions" else dialect, response) == expected
    assert provider.requests == []
    assert gateway.events(0) == []


def test_unknown_model_is_denied_and_metered_without_an_upstream_request(gateway: Gateway):
    provider = gateway.add_provider()
    gateway.start()
    response = gateway.request(model="unknown")
    assert response.status_code == 404
    assert error_of("openai_chat_completions", response) == "unknown_model"
    assert provider.requests == []
    (event,) = gateway.events(1)
    assert (event.status, event.model_id, event.provider_id, event.credential_id) == ("denied", "unknown", "", None)


@pytest.mark.parametrize("content", [b"{", b"[]", b"\xff"])
def test_malformed_request_does_not_reach_the_provider_and_service_recovers(gateway: Gateway, content: bytes):
    provider = gateway.add_provider()
    gateway.start()
    response = httpx.post(f"{gateway.url}/inf/v1/chat/completions", headers=gateway.headers(), content=content)
    assert response.status_code == 400
    assert provider.requests == []
    assert gateway.events(0) == []
    assert gateway.request().status_code == 200
    assert gateway.events(1)[0].status == "ok"
