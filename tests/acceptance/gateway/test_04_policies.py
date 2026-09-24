from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from gateway_harness import DIALECTS, FAMILIES, error_of, request_body

if TYPE_CHECKING:
    from gateway_harness import Dialect, Gateway
    from upstream import Family


INPUT_TOKEN_LIMITS: dict[Dialect, str] = {
    "openai_chat_completions": "max_completion_tokens",
    "openai_responses": "max_output_tokens",
    "anthropic": "max_tokens",
}
OUTPUT_TOKEN_LIMITS: dict[Family, str] = {
    "openai_compatible": "max_tokens",
    "openai_responses": "max_output_tokens",
    "anthropic": "max_tokens",
}


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(("limit", "expected"), [(7, 200), (8, 200), (9, 403)], ids=["below", "at", "above"])
def test_native_token_limits_are_enforced_before_upstream_translation(gateway: Gateway, dialect: Dialect, family: Family, limit: int, expected: int):
    provider = gateway.add_provider(family)
    gateway.add_policy([{"kind": "request_limits", "max_output_tokens": 8}])
    gateway.start()
    response = gateway.request(dialect, body={**request_body(dialect), INPUT_TOKEN_LIMITS[dialect]: limit})
    assert response.status_code == expected, response.text
    (event,) = gateway.events(1)
    assert event.status == ("ok" if expected == 200 else "denied")
    if expected == 200:
        assert provider.requests[0].body[OUTPUT_TOKEN_LIMITS[family]] == limit
        assert event.max_output_tokens == limit
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
        assert response.json()["gateway"]["adjustments"][0]["param"] == "temperature"
    assert gateway.events(1)[0].status == ("denied" if strict else "ok")


@pytest.mark.parametrize("family", FAMILIES)
def test_model_caps_clamp_a_permitted_limit_before_sending_it(gateway: Gateway, family: Family):
    provider = gateway.add_provider(family)
    gateway.taxonomy["models"][0]["max_output_tokens"] = 8
    gateway.start()
    response = gateway.request(max_completion_tokens=9)
    assert response.status_code == 200, response.text
    assert provider.requests[0].body[OUTPUT_TOKEN_LIMITS[family]] == 8
    assert response.json()["gateway"]["adjustments"][0] == {
        "param": "max_output_tokens",
        "action": "clamped",
        "detail": "model caps output at 8 tokens",
        "source": "model",
    }
    event = gateway.events(1)[0]
    assert (event.status, event.max_output_tokens) == ("ok", 8)


@pytest.mark.parametrize(
    ("policy_limit", "model_limit", "expected", "source"),
    [
        (8, 16, 8, "policy"),
        (16, 8, 8, "model"),
        (8, 8, 8, "policy_and_model"),
        (None, 8, 8, "model"),
    ],
)
def test_omitted_caller_limit_sends_the_tightest_available_ceiling(
    gateway: Gateway,
    policy_limit: int | None,
    model_limit: int,
    expected: int,
    source: str,
):
    provider = gateway.add_provider()
    gateway.taxonomy["models"][0]["max_output_tokens"] = model_limit
    if policy_limit is not None:
        gateway.add_policy([{"kind": "request_limits", "max_output_tokens": policy_limit}])
    gateway.start()

    response = gateway.request()

    assert response.status_code == 200, response.text
    assert provider.requests[0].body["max_tokens"] == expected
    adjustment = response.json()["gateway"]["adjustments"][0]
    assert (adjustment["action"], adjustment["source"]) == ("defaulted", source)
    assert gateway.events(1)[0].max_output_tokens == expected


def test_omitted_caller_limit_stays_unspecified_without_any_ceiling(gateway: Gateway):
    provider = gateway.add_provider()
    gateway.taxonomy["models"][0]["max_output_tokens"] = None
    gateway.start()

    response = gateway.request()

    assert response.status_code == 200, response.text
    assert "max_tokens" not in provider.requests[0].body
    assert response.json()["gateway"]["adjustments"] == []
    assert gateway.events(1)[0].max_output_tokens is None


def test_multiple_matching_policies_send_the_tightest_ceiling(gateway: Gateway):
    provider = gateway.add_provider()
    gateway.taxonomy["models"][0]["max_output_tokens"] = 32
    gateway.add_policy([{"kind": "request_limits", "max_output_tokens": 16}])
    gateway.add_policy([{"kind": "request_limits", "max_output_tokens": 8}])
    gateway.start()

    response = gateway.request()

    assert response.status_code == 200, response.text
    assert provider.requests[0].body["max_tokens"] == 8


def test_openai_chat_rejects_ambiguous_output_limits_before_upstream(gateway: Gateway):
    provider = gateway.add_provider()
    gateway.start()

    response = gateway.request(
        "openai_chat_completions",
        body={**request_body("openai_chat_completions"), "max_tokens": 8, "max_completion_tokens": 9},
    )

    assert response.status_code == 400
    assert error_of("openai_chat_completions", response) == "invalid_request"
    assert provider.requests == []


def test_anthropic_rejects_a_missing_output_limit_before_upstream(gateway: Gateway):
    provider = gateway.add_provider()
    gateway.start()

    response = gateway.request("anthropic", body={"model": "model-a", "messages": [{"role": "user", "content": "hi"}]})

    assert response.status_code == 400
    assert error_of("anthropic", response) == "invalid_request"
    assert provider.requests == []
