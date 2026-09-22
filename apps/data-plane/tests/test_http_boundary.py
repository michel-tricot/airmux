from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest
from aioresponses import CallbackResult
from anthropic import Anthropic
from conftest import TEXT_LOG, TEXT_NONSTREAM, GatewayTransport, make_outbox, mock_control_plane, read_and_close_outbox
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from data_plane.http import ObservedRoute, ResponseHeadersMiddleware
from data_plane.metrics import DataPlaneMetrics

INFERENCE_ROUTES = (
    ("POST", "/inf/v1/chat/completions"),
    ("POST", "/inf/v1/responses"),
    ("POST", "/inf/v1/messages"),
    ("GET", "/inf/v1/models"),
    ("GET", "/inf/v1/models/gpt-test"),
)


def assert_private_headers(response):
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert UUID(response.headers["x-request-id"]).version == 7


def test_response_headers_preserve_binary_content_and_known_retry_timing():
    async def limited(request):
        return Response(b"\x00\xff", status_code=429, media_type="application/octet-stream", headers={"Retry-After": "7", "Cache-Control": "public"})

    app = ResponseHeadersMiddleware(Starlette(routes=[Route("/", limited)]), DataPlaneMetrics())
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 429
    assert response.content == b"\x00\xff"
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["retry-after"] == "7"
    assert_private_headers(response)


@pytest.mark.parametrize(("method", "path"), INFERENCE_ROUTES)
def test_all_inference_authentication_errors_have_common_headers(http_mock, dp_app, method, path):
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        response = client.request(method, path)
    assert response.status_code == 401
    assert_private_headers(response)
    assert response.headers["www-authenticate"] == 'Bearer realm="airmux"'
    assert response.headers["content-type"].startswith("application/json")
    if path.endswith("/messages"):
        assert response.json()["type"] == "error"
        assert response.json()["error"]["type"] == "missing_bearer_token"
    else:
        assert response.json()["error"]["type"] == "invalid_request_error"
        assert response.json()["error"]["code"] == "missing_bearer_token"


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/metrics"])
def test_operational_routes_remain_public_and_disable_caching(http_mock, dp_app, path):
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        response = client.get(path)
    assert response.status_code == 200
    assert_private_headers(response)
    assert "www-authenticate" not in response.headers


def test_metrics_are_prometheus_compatible_and_bounded(http_mock, dp_app):
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        client.get("/inf/v1/models")
        metrics = client.get("/metrics").text

    assert 'airmux_data_plane_http_requests_total{dialect="openai_chat_completions",method="GET",outcome="rejected",route="/inf/v1/models"' in metrics
    assert "airmux_data_plane_bundle_snapshots 1.0" in metrics
    assert not any(forbidden in metrics for forbidden in ("org_id=", "workspace_id=", "model=", "provider=", "bundle_id="))


def test_native_anthropic_key_header_authenticates_inference(http_mock, dp_app, api_key):
    mock_control_plane(http_mock)
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, payload=TEXT_NONSTREAM, repeat=True)
    with TestClient(dp_app) as gateway, httpx.Client(transport=GatewayTransport(gateway)) as client:
        sdk = Anthropic(base_url="http://testserver/inf", api_key=api_key, http_client=client, max_retries=0)
        message = sdk.messages.create(model="gpt-test", max_tokens=16, messages=[{"role": "user", "content": "hi"}])
    assert message.content[0].type == "text"
    assert message.content[0].text == "héllo \U0001f30d world"


@pytest.mark.parametrize(
    ("credentials", "cookie", "status"),
    [
        ({"authorization": "Bearer {key}", "x-api-key": "sk-inf-other"}, "sk-inf-other", 200),
        ({"authorization": "Basic ignored", "x-api-key": "{key}"}, "sk-inf-other", 200),
        ({}, "{key}", 200),
        ({"authorization": "Bearer sk-inf-other", "x-api-key": "{key}"}, "{key}", 401),
        ({"authorization": "Bearer ", "x-api-key": "{key}"}, "sk-inf-other", 200),
        ({"authorization": "", "x-api-key": ""}, "{key}", 200),
    ],
)
def test_credentials_use_bearer_then_api_key_then_cookie(http_mock, booted, credentials, cookie, status):
    mock_control_plane(http_mock)
    credentials = {name: value.format(key=booted.api_key) for name, value in credentials.items()}
    with TestClient(booted.app) as client:
        client.cookies.set("airmux_playground", cookie.format(key=booted.api_key))
        response = client.get(
            "/inf/v1/models",
            headers={**credentials, "x-requested-with": "console", "sec-fetch-site": "same-origin"},
        )
    assert response.status_code == status
    if status == 401:
        assert response.json()["error"]["code"] == "invalid_token"
    assert_private_headers(response)


@pytest.mark.parametrize("stream", [False, True])
def test_request_id_matches_response_and_usage_accounting(http_mock, booted, tmp_path, http_client, stream):
    mock_control_plane(http_mock)
    http_mock.post(
        "https://api.openai.com/v1/chat/completions",
        callback=lambda _url, **_kwargs: CallbackResult(status=200, body=TEXT_LOG) if stream else CallbackResult(status=200, payload=TEXT_NONSTREAM),
        repeat=True,
    )
    with TestClient(booted.app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"authorization": f"Bearer {booted.api_key}", "x-request-id": "caller-controlled-id"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}], "stream": stream},
        )
    assert response.status_code == 200
    request_id = UUID(response.headers["x-request-id"])
    assert request_id.version == 7
    if stream:
        assert response.headers["cache-control"] == "no-store, no-transform"
        assert response.headers["x-accel-buffering"] == "no"
        assert response.headers["content-type"].startswith("text/event-stream")
        chunks = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
        assert {chunk["id"] for chunk in chunks} == {str(request_id)}
    else:
        assert_private_headers(response)
        assert response.json()["id"] == "chatcmpl-9"
        assert "x-accel-buffering" not in response.headers
    events = read_and_close_outbox(make_outbox(tmp_path, http_client))
    assert len(events) == 1
    assert events[0].request_id == request_id


def test_policy_denials_have_the_same_request_id_as_the_usage_event(http_mock, dp_app, api_key, tmp_path, http_client):
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"authorization": f"Bearer {api_key}"},
            json={"model": "unknown", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 404
    assert_private_headers(response)
    events = read_and_close_outbox(make_outbox(tmp_path, http_client))
    assert events[0].request_id == UUID(response.headers["x-request-id"])


def test_unexpected_errors_still_have_private_headers(http_mock, dp_app, api_key):
    mock_control_plane(http_mock)
    http_mock.post("https://api.openai.com/v1/chat/completions", exception=RuntimeError("private internal detail"), repeat=True)
    with TestClient(dp_app, raise_server_exceptions=False) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 500
    assert_private_headers(response)
    assert "private internal detail" not in response.text


def test_each_request_gets_a_distinct_gateway_id(http_mock, dp_app, api_key):
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        headers = {"authorization": f"Bearer {api_key}", "x-request-id": "same-caller-id"}
        first = client.get("/inf/v1/models", headers=headers)
        second = client.get("/inf/v1/models", headers=headers)
    assert UUID(first.headers["x-request-id"]).version == UUID(second.headers["x-request-id"]).version == 7
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


@pytest.mark.parametrize(
    ("method", "path", "status", "route"),
    [
        ("GET", "/items/one", 200, "/items/{name}"),
        ("POST", "/items/one", 405, "unmatched"),
        ("GET", "/missing", 404, "unmatched"),
        ("GET", "/items/one/", 307, "unmatched"),
    ],
)
def test_route_metrics_preserve_templates_and_unmatched_requests(method, path, status, route):
    metrics = DataPlaneMetrics()

    async def endpoint(request):
        assert request.state.metrics_route == "/items/{name}"
        assert 'airmux_data_plane_inflight_requests{route="/items/{name}",stream="false"} 1.0' in metrics.render().decode()
        return Response("ok")

    app = Starlette(routes=[ObservedRoute("/items/{name}", endpoint)])
    app.state.metrics = metrics
    try:
        with TestClient(ResponseHeadersMiddleware(app, metrics)) as client:
            response = client.request(method, path, follow_redirects=False)
        assert response.status_code == status
        rendered = metrics.render().decode()
        assert f'route="{route}",status_class="{status // 100}xx",stream="false"}} 1.0' in rendered
        assert f'airmux_data_plane_inflight_requests{{route="{route}",stream="false"}} 0.0' in rendered
        assert_private_headers(response)
    finally:
        metrics.shutdown()
