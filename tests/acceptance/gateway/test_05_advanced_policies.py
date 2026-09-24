from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from gateway_harness import DIALECTS, INFERENCE_KEY, SECOND_KEY, error_of, eventually

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
def test_allow_rule_never_overrides_an_independent_restriction(gateway: Gateway, dialect: Dialect):
    provider = gateway.add_provider()
    gateway.add_policy([{"kind": "models", "names": ["model-a", "model-b"]}])
    gateway.add_policy([{"kind": "price_limit", "max_input_price_per_mtok": "1", "max_output_price_per_mtok": "5"}])
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
    gateway.add_policy([{"kind": "models", "names": ["model-b", "model-c"]}])
    gateway.start()
    for model, status in (("model-a", 403), ("model-b", 200), ("model-c", 403)):
        assert gateway.request(dialect, model=model).status_code == status
    assert [request.body["model"] for request in provider.requests] == ["upstream-model-b"]
    assert [event.status for event in gateway.events(3)] == ["denied", "ok", "denied"]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_user_policy_covers_multiple_credentials_and_adopts_identity_changes(gateway: Gateway, dialect: Dialect, stream: bool):
    provider = gateway.add_provider()
    user_id = gateway.bundle["keys"][0]["user_id"]
    other_user_id = gateway.bundle["keys"][1]["user_id"]
    third_key = "sk-inf-another-user-credential"
    gateway.bundle["keys"] = [*gateway.bundle["keys"], {"token": third_key, "user_id": user_id}]
    gateway.add_policy([{"kind": "models", "names": ["model-a", "model-b"]}], target={"kind": "workspace"})
    gateway.add_policy([{"kind": "models", "names": ["model-b"]}], target={"kind": "selected_users", "user_ids": [user_id]})
    gateway.start()
    for key in (INFERENCE_KEY, third_key):
        assert gateway.request(dialect, key=key, stream=stream).status_code == 403
        permitted = gateway.request(dialect, key=key, model="model-b", stream=stream)
        assert permitted.status_code == 200, permitted.text
    assert gateway.request(dialect, key=SECOND_KEY, stream=stream).status_code == 200
    discovered = gateway.headers(key=INFERENCE_KEY)
    assert [model["id"] for model in httpx.get(f"{gateway.url}/inf/v1/models", headers=discovered).json()["data"]] == ["model-b"]
    gateway.bundle["keys"][0]["user_id"] = other_user_id
    gateway.write_files()
    eventually(lambda: gateway.request(dialect, stream=stream).status_code == 200)
    assert gateway.request(dialect, key=third_key, stream=stream).status_code == 403
    assert len(provider.requests) >= 4
