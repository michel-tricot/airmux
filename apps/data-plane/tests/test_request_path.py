from __future__ import annotations

import json
import time

import pytest
from conftest import (
    MODEL,
    ORG,
    PLATFORM_CREDENTIAL,
    PROVIDER,
    WORKSPACE,
    make_bundle,
    make_config,
    make_key,
    make_outbox,
    mock_control_plane,
    read_and_close_outbox,
)
from prometheus_client.parser import text_string_to_metric_families
from starlette.testclient import TestClient
from yarl import URL

import data_plane.app as app_module
from airmux_runtime.secrets import Secret
from contract import BundleV1, Catalog, uuid7
from contract.policies import BudgetAggregation, PolicyDefinition, PolicyEntry
from data_plane.app import create_app
from data_plane.cache import CachedBundles, write_cached_bundles
from data_plane.canonical import CanonicalRequest
from data_plane.config import ControlPlaneBudgetConfig
from data_plane.control_plane_link import ControlPlaneLink
from data_plane.egress import REGISTRY
from data_plane.metrics import DataPlaneMetrics
from data_plane.outbox import DevNullOutbox, OutboxFullError
from data_plane.proxy import RequestRejectedError, _transform


def _recorded(tmp_path, http_client):
    return read_and_close_outbox(make_outbox(tmp_path, http_client))


OPENAI_RESPONSE = {
    "id": "chatcmpl-123",
    "model": "gpt-real",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello there"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
}


def _budget_bundle(aggregation: BudgetAggregation) -> BundleV1:
    _, key = make_key()
    policy = PolicyEntry(
        id=uuid7(),
        workspace_id=WORKSPACE,
        name="Advisory budget",
        priority=100,
        definition=PolicyDefinition.model_validate(
            {
                "target": {"kind": "workspace"},
                "rules": [
                    {
                        "match": {"kind": "all_requests"},
                        "action": {"kind": "budget", "period": "month", "amount_usd": "0.01", "aggregation": aggregation},
                    }
                ],
            }
        ),
    )
    catalog = Catalog(providers=[PROVIDER], models=[MODEL], credentials=[PLATFORM_CREDENTIAL])
    return make_bundle(keys=[key], catalog=catalog).model_copy(update={"policies": (policy,)})


@pytest.mark.parametrize("path", ["chat/completions", "responses", "messages"])
def test_inference_routes_use_the_inference_prefix(http_mock, dp_app, path):
    mock_control_plane(http_mock)
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


def test_chat_completion_end_to_end(http_mock, api_key, dp_app, tmp_path, http_client):
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, payload=OPENAI_RESPONSE, repeat=True)
    mock_control_plane(http_mock)
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
    sent = json.loads(http_mock.requests.get(("POST", URL("https://api.openai.com/v1/chat/completions")), [])[-1].kwargs["data"])
    assert sent["model"] == "gpt-real"
    assert (
        http_mock.requests.get(("POST", URL("https://api.openai.com/v1/chat/completions")), [])[-1].kwargs["headers"]["authorization"]
        == "Bearer sk-test-not-real"
    )


@pytest.mark.parametrize("aggregation", ["shared", "per_key"])
def test_no_budget_backend_accepts_budget_policies(http_mock, api_key, dp_app, tmp_path, aggregation):
    write_cached_bundles(tmp_path, CachedBundles(bundles=[_budget_bundle(aggregation)]))
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, payload=OPENAI_RESPONSE, repeat=True)
    mock_control_plane(http_mock)

    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "say hi"}]},
        )

    assert response.status_code == 200
    assert len(http_mock.requests.get(("POST", URL("https://api.openai.com/v1/chat/completions")), [])) == 1


def test_unavailable_budget_state_does_not_reject_inference(http_mock, tmp_path, monkeypatch):
    api_key, _ = make_key()
    write_cached_bundles(tmp_path, CachedBundles(bundles=[_budget_bundle("shared")]))
    control_plane = ControlPlaneLink(url="http://cp.test", management_key="dp-token")
    config = make_config(tmp_path).model_copy(update={"budget": ControlPlaneBudgetConfig(control_plane=control_plane, poll_interval_s=60)})
    monkeypatch.setenv("P1_API_KEY", "sk-test-not-real")
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, payload=OPENAI_RESPONSE, repeat=True)
    mock_control_plane(http_mock)

    with TestClient(create_app(config)) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "say hi"}]},
        )
        metrics = client.get("/metrics").text

    assert response.status_code == 200
    assert len(http_mock.requests.get(("POST", URL("https://api.openai.com/v1/chat/completions")), [])) == 1
    assert 'airmux_data_plane_budget_state_fallbacks_total{reason="missing"} 1.0' in metrics


def test_metrics_report_the_pending_event_backlog(http_mock, api_key, dp_app):
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, payload=OPENAI_RESPONSE, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "say hi"}]},
        )
        deadline = time.monotonic() + 2
        while True:
            metrics = client.get("/metrics")
            samples = {sample.name: sample.value for family in text_string_to_metric_families(metrics.text) for sample in family.samples}
            if samples["airmux_data_plane_metering_outbox_pending"] == 1:
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)

    assert response.status_code == 200
    assert metrics.status_code == 200
    assert samples["airmux_data_plane_metering_outbox_oldest_age_seconds"] >= 0
    assert samples["airmux_data_plane_metering_writer_queue_capacity"] == 10_000
    assert 'airmux_data_plane_metering_admission_total{outcome="accepted"} 1.0' in metrics.text


@pytest.mark.parametrize("model", ["gpt-test", "ghost"])
def test_metering_capacity_is_rejected_before_the_provider_call(http_mock, api_key, dp_app, monkeypatch, model):
    outbox = DevNullOutbox(DataPlaneMetrics())

    def reject_reservation():
        raise OutboxFullError

    monkeypatch.setattr(outbox, "reserve", reject_reservation)
    monkeypatch.setattr(app_module, "build_outbox", lambda *_args: outbox)
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, payload=OPENAI_RESPONSE, repeat=True)
    mock_control_plane(http_mock)

    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": "say hi"}]},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "metering_capacity_exhausted"
    assert len(http_mock.requests.get(("POST", URL("https://api.openai.com/v1/chat/completions")), [])) == 0


def test_malformed_buffered_provider_response_is_rejected(http_mock, api_key, dp_app, tmp_path, http_client):
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, payload={}, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "say hi"}]},
        )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_upstream_response"
    assert [event.status for event in _recorded(tmp_path, http_client)] == ["upstream_error"]


def test_missing_token_rejected(http_mock, api_key, dp_app):
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        r = client.post("/inf/v1/chat/completions", json={"model": "gpt-test", "messages": []})
    assert r.status_code == 401


def test_bearer_authentication_scheme_is_case_insensitive(http_mock, api_key, dp_app):
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, payload=OPENAI_RESPONSE, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 200


def test_dialect_header_has_no_special_behavior(http_mock, api_key, dp_app):
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, payload=OPENAI_RESPONSE, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "X-airmux-Dialect": "unknown"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 200
    assert response.json()["object"] == "chat.completion"


def test_chat_completion_path_does_not_route_by_request_shape(http_mock, api_key, dp_app):
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "input": "hi"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert response.json()["error"]["code"] == "invalid_request"


def test_same_origin_playground_cookie_authenticates(http_mock, api_key, dp_app):
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, payload=OPENAI_RESPONSE, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        client.cookies.set("airmux_playground", api_key)
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"X-Requested-With": "airmux-console", "Sec-Fetch-Site": "same-origin"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "say hi"}]},
        )
    assert response.status_code == 200


def test_playground_cookie_rejects_cross_site_requests(http_mock, api_key, dp_app):
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        client.cookies.set("airmux_playground", api_key)
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"X-Requested-With": "airmux-console", "Sec-Fetch-Site": "cross-site"},
            json={"model": "gpt-test", "messages": []},
        )
    assert response.status_code == 403


def test_upstream_error_passed_through(http_mock, api_key, dp_app):
    http_mock.post("https://api.openai.com/v1/chat/completions", status=429, payload={"error": {"code": "rate_limited"}}, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        r = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 429


def test_policy_denial_is_metered(http_mock, api_key, dp_app, tmp_path, http_client):
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        r = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "ghost", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 404  # unknown model
    events = _recorded(tmp_path, http_client)
    assert [(e.status, e.model_id, e.key_id, e.workspace_id) for e in events] == [("denied", "ghost", make_key()[1].key_id, WORKSPACE)]


def test_upstream_timeout_is_metered_as_timeout(http_mock, api_key, dp_app, tmp_path, http_client):
    http_mock.post("https://api.openai.com/v1/chat/completions", exception=TimeoutError("timed out"), repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        r = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 504
    events = _recorded(tmp_path, http_client)
    assert [e.status for e in events] == ["timeout"]


def test_credential_timeout_without_fallback_preserves_gateway_error(http_mock, api_key, dp_app, monkeypatch):
    async def credential_timeout(entry, resolver):
        raise TimeoutError

    monkeypatch.setattr("data_plane.proxy._resolve_credential", credential_timeout)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "fallback_deadline_exceeded"
