from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from gateway_harness import DIALECTS, FAMILIES, error_of, request_body

if TYPE_CHECKING:
    from gateway_harness import Dialect, Gateway
    from upstream import Family


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(("limit", "expected"), [(7, 200), (8, 200), (9, 403)], ids=["below", "at", "above"])
def test_native_token_limits_are_enforced_before_upstream_translation(gateway: Gateway, dialect: Dialect, family: Family, limit: int, expected: int):
    provider = gateway.add_provider(family)
    gateway.add_policy([{"kind": "request_limits", "max_output_tokens": 8}])
    gateway.start()
    parameter = "max_completion_tokens" if dialect == "openai_native" else "max_output_tokens" if dialect == "openai_responses" else "max_tokens"
    response = gateway.request(dialect, body={**request_body(dialect), parameter: limit})
    assert response.status_code == expected, response.text
    (event,) = gateway.events(1)
    assert event.status == ("ok" if expected == 200 else "denied")
    if expected == 200:
        assert provider.requests[0].body["max_output_tokens" if family == "openai_responses" else "max_tokens"] == limit
    else:
        assert error_of(dialect, response) == "policy_denied"
        assert provider.requests == []
        assert (event.input_tokens, event.output_tokens, event.cost_usd) == (0, 0, 0)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
@pytest.mark.parametrize(
    "action",
    [
        {"kind": "models", "names": ["model-b"]},
        {"kind": "providers", "names": ["backup"]},
        {"kind": "deny", "message": "Restricted by policy"},
        {"kind": "price_limit", "max_input_price_per_mtok": "1", "max_output_price_per_mtok": "5"},
    ],
    ids=["model_allowlist", "provider_allowlist", "deny", "price_limit"],
)
def test_individual_restrictions_deny_without_an_upstream_request(gateway: Gateway, dialect: Dialect, stream: bool, action: dict[str, object]):
    provider = gateway.add_provider()
    gateway.add_provider(name="backup", models=("model-c",))
    gateway.add_policy([action])
    gateway.start()
    response = gateway.request(dialect, stream=stream)
    assert response.status_code == 403, response.text
    assert error_of(dialect, response) == "policy_denied"
    assert provider.requests == []
    (event,) = gateway.events(1)
    assert event.status == "denied"
    assert event.credential_scope is None


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("strict", [False, True], ids=["adjust", "strict"])
def test_unsupported_parameters_are_adjusted_or_rejected_by_policy(gateway: Gateway, dialect: Dialect, family: Family, strict: bool):
    provider = gateway.add_provider(family)
    gateway.taxonomy["models"][0]["parameter_support"] = {"temperature": "unsupported"}
    if strict:
        gateway.add_policy([{"kind": "strict_parameters"}])
    gateway.start()
    response = gateway.request(dialect, temperature=0.5)
    assert response.status_code == (403 if strict else 200), response.text
    if strict:
        assert provider.requests == []
    else:
        assert "temperature" not in provider.requests[0].body
        if dialect == "canonical":
            assert response.json()["gateway"]["adjustments"][0]["param"] == "temperature"
    assert gateway.events(1)[0].status == ("denied" if strict else "ok")


@pytest.mark.parametrize("family", FAMILIES)
def test_model_caps_clamp_a_permitted_limit_before_sending_it(gateway: Gateway, family: Family):
    provider = gateway.add_provider(family)
    gateway.taxonomy["models"][0]["max_output_tokens"] = 8
    gateway.start()
    response = gateway.request(max_tokens=9)
    assert response.status_code == 200, response.text
    assert provider.requests[0].body["max_output_tokens" if family == "openai_responses" else "max_tokens"] == 8
    assert response.json()["gateway"]["adjustments"][0]["action"] == "clamped"
    assert gateway.events(1)[0].status == "ok"
