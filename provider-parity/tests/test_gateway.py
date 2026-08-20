from __future__ import annotations

import yaml

from provider_parity.gateway import render_bundle
from provider_parity.models import Target


def test_local_bundle_routes_the_gateway_model_to_the_same_provider_surface():
    target = Target(
        provider_id="anthropic",
        surface_id="anthropic",
        endpoint="messages",
        egress_kind="anthropic",
        base_url="https://api.anthropic.com/v1",
        credential_env="ANTHROPIC_API_KEY",
        auth="header_key:x-api-key",
        headers={"anthropic-version": "2023-06-01"},
        model_id="anthropic/claude-test",
        upstream_model="claude-test",
        context_window=200000,
        max_output_tokens=8192,
        input_modalities=frozenset({"text"}),
        capabilities=frozenset({"streaming", "tools"}),
        parameter_support={"temperature": "supported"},
    )

    bundle = yaml.safe_load(render_bundle([target], "sk-inf-parity"))

    assert bundle["providers"] == [{"provider_id": "anthropic", "kind": "anthropic", "base_url": "https://api.anthropic.com/v1"}]
    assert bundle["models"][0]["model_id"] == "anthropic/claude-test"
    assert bundle["models"][0]["upstream_model"] == "claude-test"
    assert bundle["models"][0]["parameter_support"] == {"temperature": "supported"}
