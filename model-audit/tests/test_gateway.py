from __future__ import annotations

import pytest

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
