from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from live_harness import CASES, RecordingProvider
from tests.acceptance.gateway.gateway_harness import FAMILIES

if TYPE_CHECKING:
    from live_harness import LiveGateway, RequestBudget
    from tests.acceptance.gateway.upstream import Family

OTHER_FAMILIES: dict[Family, Family] = {"openai_compatible": "anthropic", "openai_responses": "anthropic", "anthropic": "openai_responses"}


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_live_denial_never_reaches_a_provider(live_gateway: LiveGateway, stream: bool) -> None:
    live_gateway.gateway.add_policy([{"kind": "deny", "message": "live test denial"}])
    live_gateway.gateway.start()
    assert live_gateway.request(stream=stream).status_code == 403
    assert live_gateway.provider.deliveries == []
    (event,) = live_gateway.gateway.events(1)
    assert event.status == "denied"
    assert (event.input_tokens, event.output_tokens, event.cost_usd) == (0, 0, 0)


@pytest.mark.parametrize("family", FAMILIES)
def test_live_output_limit_is_enforced_and_forwarded(live_gateway: LiveGateway) -> None:
    live_gateway.gateway.add_policy([{"kind": "request_limits", "max_output_tokens": 32}])
    live_gateway.gateway.start()
    assert live_gateway.request(max_output_tokens=33).status_code == 403
    assert live_gateway.provider.deliveries == []
    response = live_gateway.request(max_output_tokens=32)
    assert response.status_code == 200, response.text
    denied, accepted = live_gateway.gateway.events(2)
    assert denied.status == "denied"
    assert denied.cost_usd == 0
    assert live_gateway.provider.deliveries[0].request[live_gateway.case.output_limit] == 32
    assert accepted.output_tokens <= 32
    live_gateway.assert_metering(accepted)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_live_fallback_crosses_families_and_meters_the_real_provider(
    live_gateway: LiveGateway, family: Family, stream: bool, request_budget: RequestBudget
) -> None:
    primary = RecordingProvider(CASES[OTHER_FAMILIES[family]], request_budget, unavailable=True)
    live_gateway.providers.append(primary)
    live_gateway.gateway.environment["FAULT_API_KEY"] = "sk-live-test-fault"
    live_gateway.gateway.taxonomy["providers"].append({"provider_id": "fault", "kind": OTHER_FAMILIES[family], "base_url": primary.url})
    live_gateway.gateway.taxonomy["models"].append({**live_gateway.gateway.taxonomy["models"][0], "model_id": "primary", "provider_id": "fault"})
    live_gateway.gateway.add_policy(
        [{"kind": "fallback", "models": ["model-a"], "on": ["upstream_unavailable"], "max_attempts": 2, "timeout_ms": 90000}]
    )
    live_gateway.gateway.start()
    response = live_gateway.request(model="primary", stream=stream)
    assert response.status_code == 200, response.text
    first, second = live_gateway.gateway.events(2)
    assert first.status == "upstream_error"
    assert first.provider_id == "fault"
    assert first.output_tokens == 0
    assert first.request_id == second.request_id
    assert first.credential_id != second.credential_id
    assert len(primary.deliveries) == 1
    assert primary.deliveries[0].status == 503
    live_gateway.assert_metering(second)
