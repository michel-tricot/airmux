from __future__ import annotations

from typing import Literal

from model_audit.drivers.base import Connection, status_failure


def connection(route: Literal["direct", "gateway"]) -> Connection:
    return Connection(base_url="https://example.test", api_key="key", auth="bearer", headers={}, route=route)


def test_status_failure_attributes_provider_and_gateway_origins():
    direct = status_failure(connection("direct"), 400, "invalid_request", "bad option")
    gateway = status_failure(connection("gateway"), 502, "bad_gateway", "upstream unavailable")

    assert direct.origin == "direct"
    assert direct.kind == "rejection"
    assert direct.retryable is False
    assert gateway.origin == "gateway"
    assert gateway.kind == "gateway"
    assert gateway.retryable is True


def test_status_failure_identifies_access_failures():
    failure = status_failure(connection("gateway"), 401, "invalid_token", "bad key")

    assert failure.kind == "access"
    assert failure.code == "gateway_authentication"
