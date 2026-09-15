from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from gateway_harness import DIALECTS, SECOND_KEY, error_of

if TYPE_CHECKING:
    from gateway_harness import Dialect, Gateway


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_selected_key_policy_does_not_restrict_other_keys(gateway: Gateway, dialect: Dialect, stream: bool):
    provider = gateway.add_provider()
    gateway.add_policy([{"kind": "models", "names": ["model-b"]}], target={"kind": "selected_keys", "key_ids": ["local-0"]})
    gateway.start()
    restricted = gateway.request(dialect, stream=stream)
    permitted = gateway.request(dialect, stream=stream, key=SECOND_KEY)
    assert restricted.status_code == 403
    assert permitted.status_code == 200, permitted.text
    assert len(provider.requests) == 1
    events = gateway.events(2)
    assert [(event.key_id, event.status) for event in events] == [("local-0", "denied"), ("local-1", "ok")]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("priorities", [(10, 100), (100, 10)], ids=["allow_first", "deny_first"])
def test_allow_rule_never_overrides_an_independent_restriction(gateway: Gateway, dialect: Dialect, priorities: tuple[int, int]):
    provider = gateway.add_provider()
    gateway.add_policy([{"kind": "models", "names": ["model-a", "model-b"]}], priority=priorities[0])
    gateway.add_policy([{"kind": "price_limit", "max_input_price_per_mtok": "1", "max_output_price_per_mtok": "5"}], priority=priorities[1])
    gateway.start()
    response = gateway.request(dialect)
    assert response.status_code == 403
    assert error_of(dialect, response) == "policy_denied"
    assert provider.requests == []
    assert gateway.events(1)[0].status == "denied"


@pytest.mark.parametrize("dialect", DIALECTS)
def test_model_and_stream_conditions_only_restrict_matching_requests(gateway: Gateway, dialect: Dialect):
    provider = gateway.add_provider()
    gateway.add_policy([{"kind": "deny", "message": "Model A cannot stream"}], match={"kind": "request", "models": ["model-a"], "stream": True})
    gateway.start()
    assert gateway.request(dialect, stream=False).status_code == 200
    assert gateway.request(dialect, stream=True).status_code == 403
    assert gateway.request(dialect, stream=True, model="model-b").status_code == 200
    assert len(provider.requests) == 2
    assert [(event.model_id, event.stream, event.status) for event in gateway.events(3)] == [
        ("model-a", False, "ok"),
        ("model-a", True, "denied"),
        ("model-b", True, "ok"),
    ]


@pytest.mark.parametrize("dialect", DIALECTS)
def test_intersecting_model_allowlists_only_permit_their_common_models(gateway: Gateway, dialect: Dialect):
    provider = gateway.add_provider(models=("model-a", "model-b", "model-c"))
    gateway.add_policy([{"kind": "models", "names": ["model-a", "model-b"]}])
    gateway.add_policy([{"kind": "models", "names": ["model-b", "model-c"]}], priority=200)
    gateway.start()
    for model, status in (("model-a", 403), ("model-b", 200), ("model-c", 403)):
        assert gateway.request(dialect, model=model).status_code == status
    assert [request.body["model"] for request in provider.requests] == ["upstream-model-b"]
    assert [event.status for event in gateway.events(3)] == ["denied", "ok", "denied"]
