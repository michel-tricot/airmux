from __future__ import annotations

from dataclasses import replace

import pytest

from model_audit.drivers.base import access_error, status_outcome
from model_audit.gateway import Gateway


@pytest.mark.parametrize(
    ("endpoint", "dialect"),
    [
        ("chat/completions", "openai_native"),
        ("responses", "openai_responses"),
        ("messages", "anthropic"),
    ],
)
def test_raw_gateway_connections_select_the_requested_dialect(endpoint, dialect):
    connection = Gateway(base_url="http://gateway", api_key="key").connection(endpoint)

    assert connection.headers == {"x-airllm-dialect": dialect}


def test_provider_forbidden_response_does_not_invalidate_gateway_authentication():
    connection = Gateway(base_url="http://gateway", api_key="key").connection("chat/completions")

    assert access_error(connection, 403, "model_access_denied") is None
    assert status_outcome(connection, 403, "model_access_denied") == "error"


def test_direct_feature_forbidden_response_does_not_invalidate_provider_authentication():
    connection = Gateway(base_url="http://gateway", api_key="key").connection("chat/completions")
    direct = replace(connection, route="direct")

    assert access_error(direct, 403, "permission_denied") is None
    assert status_outcome(direct, 403, "permission_denied") == "error"
    assert access_error(direct, 401, "invalid_api_key") == "direct_authentication"


@pytest.mark.parametrize("code", ["credit_balance_exhausted", "insufficient_quota", "billing_hard_limit_reached"])
def test_provider_billing_failures_are_not_transient(code):
    connection = Gateway(base_url="http://gateway", api_key="key").connection("chat/completions")

    assert access_error(connection, 429, code) == "provider_billing_access"
    assert status_outcome(connection, 429, code) == "inconclusive"


@pytest.mark.parametrize("code", ["missing_bearer_token", "missing_requested_with", "cross_site_request", "invalid_token"])
def test_gateway_authentication_codes_remain_access_failures(code):
    connection = Gateway(base_url="http://gateway", api_key="key").connection("chat/completions")

    assert access_error(connection, 403, code) == "gateway_authentication"
    assert status_outcome(connection, 403, code) == "inconclusive"
