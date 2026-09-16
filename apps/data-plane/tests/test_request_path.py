from __future__ import annotations

import json

import httpx
import pytest
import respx
from conftest import MODEL, ORG, PROVIDER, WORKSPACE, make_key, make_outbox, mock_control_plane, read_and_close_outbox
from starlette.testclient import TestClient

from airmux_runtime.secrets import Secret
import data_plane.app as app_module
from data_plane.canonical import CanonicalRequest
from data_plane.egress import REGISTRY
from data_plane.outbox import OUTBOX_CAPACITY, DevNullOutbox
from data_plane.proxy import RequestRejectedError, _transform


def _recorded(tmp_path, http_client):
    return read_and_close_outbox(make_outbox(tmp_path, http_client))


OPENAI_RESPONSE = {
    "id": "chatcmpl-123",
    "model": "gpt-real",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello there"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
}


@respx.mock
@pytest.mark.parametrize("path", ["chat/completions", "responses", "messages"])
def test_inference_routes_use_the_inference_prefix(dp_app, path):
    mock_control_plane()
    with TestClient(dp_app) as client:
        assert client.post(f"/inf/v1/{path}").status_code == 401
        assert client.post(f"/v1/{path}").status_code == 404


def test_unrepresentable_egress_request_is_a_declared_rejection():
    adapter = REGISTRY["openai_responses"](PROVIDER.model_copy(update={"kind": "openai_responses"}), Secret("sk-test"))
    request = CanonicalRequest.model_validate({"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}], "stop": ["END"]})

    with pytest.raises(RequestRejectedError) as error:
        _transform(adapter, request, MODEL)

    assert error.value.status == 400
    assert error.value.code == "unsupported_feature"


@respx.mock
def test_chat_completion_end_to_end(api_key, dp_app, tmp_path, http_client):
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=OPENAI_RESPONSE))
    mock_control_plane()
    with TestClient(dp_app) as client:
        r = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "say hi"}]},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "hello there"
    assert body["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 2,
        "total_tokens": 7,
        "prompt_tokens_details": {"cached_tokens": 0},
    }
    events = _recorded(tmp_path, http_client)
    assert [(e.status, e.org_id, e.workspace_id) for e in events] == [("ok", ORG, WORKSPACE)]
    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "gpt-real"
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-test-not-real"


@respx.mock
def test_health_reports_the_pending_event_backlog(api_key, dp_app):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=OPENAI_RESPONSE))
    mock_control_plane()
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "say hi"}]},
        )
        health = client.get("/healthz")

    assert response.status_code == 200
    assert health.status_code == 200
    assert health.json()["events"]["reserved"] == 0
    assert health.json()["events"]["filled"] + health.json()["events"]["durable"] == 1
    assert health.json()["events"]["capacity"] == OUTBOX_CAPACITY
    assert health.json()["events"]["oldest_age_s"] >= 0


@respx.mock
@pytest.mark.parametrize("model", ["gpt-test", "ghost"])
def test_metering_capacity_is_rejected_before_the_provider_call(api_key, dp_app, monkeypatch, model):
    outbox = DevNullOutbox()
    held = outbox.try_reserve(OUTBOX_CAPACITY)
    assert held is not None
    monkeypatch.setattr(app_module, "build_outbox", lambda *_args: outbox)
    upstream = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=OPENAI_RESPONSE))
    mock_control_plane()

    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": "say hi"}]},
        )
        held.release_unused()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "metering_capacity_exhausted"
    assert upstream.call_count == 0


@respx.mock
def test_malformed_buffered_provider_response_is_rejected(api_key, dp_app, tmp_path, http_client):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json={}))
    mock_control_plane()
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "say hi"}]},
        )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_upstream_response"
    assert [event.status for event in _recorded(tmp_path, http_client)] == ["upstream_error"]


@respx.mock
def test_missing_token_rejected(api_key, dp_app):
    mock_control_plane()
    with TestClient(dp_app) as client:
        r = client.post("/inf/v1/chat/completions", json={"model": "gpt-test", "messages": []})
    assert r.status_code == 401


@respx.mock
def test_bearer_authentication_scheme_is_case_insensitive(api_key, dp_app):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=OPENAI_RESPONSE))
    mock_control_plane()
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 200


@respx.mock
def test_dialect_header_has_no_special_behavior(api_key, dp_app):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=OPENAI_RESPONSE))
    mock_control_plane()
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "X-airmux-Dialect": "unknown"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 200
    assert response.json()["object"] == "chat.completion"


@respx.mock
def test_chat_completion_path_does_not_route_by_request_shape(api_key, dp_app):
    mock_control_plane()
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "input": "hi"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert response.json()["error"]["code"] == "invalid_request"


@respx.mock
def test_same_origin_playground_cookie_authenticates(api_key, dp_app):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=OPENAI_RESPONSE))
    mock_control_plane()
    with TestClient(dp_app) as client:
        client.cookies.set("airmux_playground", api_key)
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"X-Requested-With": "airmux-console", "Sec-Fetch-Site": "same-origin"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "say hi"}]},
        )
    assert response.status_code == 200


@respx.mock
def test_playground_cookie_rejects_cross_site_requests(api_key, dp_app):
    mock_control_plane()
    with TestClient(dp_app) as client:
        client.cookies.set("airmux_playground", api_key)
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"X-Requested-With": "airmux-console", "Sec-Fetch-Site": "cross-site"},
            json={"model": "gpt-test", "messages": []},
        )
    assert response.status_code == 403


@respx.mock
def test_upstream_error_passed_through(api_key, dp_app):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(429, json={"error": {"code": "rate_limited"}}))
    mock_control_plane()
    with TestClient(dp_app) as client:
        r = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 429


@respx.mock
def test_policy_denial_is_metered(api_key, dp_app, tmp_path, http_client):
    mock_control_plane()
    with TestClient(dp_app) as client:
        r = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "ghost", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 404  # unknown model
    events = _recorded(tmp_path, http_client)
    assert [(e.status, e.model_id, e.key_id, e.workspace_id) for e in events] == [("denied", "ghost", make_key()[1].key_id, WORKSPACE)]


@respx.mock
def test_upstream_timeout_is_metered_as_timeout(api_key, dp_app, tmp_path, http_client):
    respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=httpx.ReadTimeout("timed out"))
    mock_control_plane()
    with TestClient(dp_app) as client:
        r = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 504
    events = _recorded(tmp_path, http_client)
    assert [e.status for e in events] == ["timeout"]
