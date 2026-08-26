from __future__ import annotations

from provider_parity.gateway import Gateway


def test_running_gateway_uses_the_configured_origin_for_each_sdk_surface():
    gateway = Gateway(base_url="http://gateway.example/", api_key="sk-inf-parity")

    openai = gateway.connection("chat/completions")
    responses = gateway.connection("responses")
    anthropic = gateway.connection("messages")

    assert openai.base_url == "http://gateway.example/inf/v1"
    assert responses.base_url == "http://gateway.example/inf/v1"
    assert anthropic.base_url == "http://gateway.example/inf/v1"
    assert {openai.api_key, responses.api_key, anthropic.api_key} == {"sk-inf-parity"}
