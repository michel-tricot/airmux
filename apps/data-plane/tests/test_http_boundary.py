from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest
import respx
from anthropic import Anthropic
from conftest import TEXT_LOG, TEXT_NONSTREAM, GatewayTransport, make_outbox, mock_control_plane
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from data_plane.http import ResponseHeadersMiddleware

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

    app = ResponseHeadersMiddleware(Starlette(routes=[Route("/", limited)]))
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 429
    assert response.content == b"\x00\xff"
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["retry-after"] == "7"
    assert_private_headers(response)


@respx.mock
@pytest.mark.parametrize(("method", "path"), INFERENCE_ROUTES)
def test_all_inference_authentication_errors_have_common_headers(dp_app, method, path):
    mock_control_plane()
    with TestClient(dp_app) as client:
        response = client.request(method, path)
    assert response.status_code == 401
    assert_private_headers(response)
    assert response.headers["www-authenticate"] == 'Bearer realm="tokkeeper"'
    assert response.headers["content-type"].startswith("application/json")
    if path.endswith("/messages"):
        assert response.json()["type"] == "error"
        assert response.json()["error"]["type"] == "missing_bearer_token"
    else:
        assert response.json()["error"]["code"] == "missing_bearer_token"


@respx.mock
@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
def test_operational_routes_remain_public_and_disable_caching(dp_app, path):
    mock_control_plane()
    with TestClient(dp_app) as client:
        response = client.get(path)
    assert response.status_code == 200
    assert_private_headers(response)
    assert "www-authenticate" not in response.headers


@respx.mock
def test_native_anthropic_key_header_authenticates_inference(dp_app, api_key):
    mock_control_plane()
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=TEXT_NONSTREAM))
    with TestClient(dp_app) as gateway, httpx.Client(transport=GatewayTransport(gateway)) as client:
        sdk = Anthropic(base_url="http://testserver/inf", api_key=api_key, http_client=client, max_retries=0)
        message = sdk.messages.create(model="gpt-test", max_tokens=16, messages=[{"role": "user", "content": "hi"}])
    assert message.content[0].type == "text"
    assert message.content[0].text == "héllo \U0001f30d world"


@respx.mock
@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "bEaReR"])
def test_matching_explicit_credentials_have_one_identity(dp_app, api_key, scheme):
    mock_control_plane()
    with TestClient(dp_app) as client:
        response = client.get("/inf/v1/models", headers={"authorization": f"{scheme} {api_key}", "x-api-key": api_key})
    assert response.status_code == 200
    assert_private_headers(response)


@respx.mock
@pytest.mark.parametrize(
    "headers",
    [
        [("authorization", "Bearer {key}"), ("x-api-key", "sk-inf-different")],
        [("authorization", "Bearer {key}"), ("authorization", "Bearer {key}")],
        [("x-api-key", "{key}"), ("x-api-key", "{key}")],
    ],
)
def test_conflicting_or_duplicate_credentials_are_rejected(dp_app, api_key, headers):
    mock_control_plane()
    with TestClient(dp_app) as client:
        response = client.get("/inf/v1/models", headers=[(name, value.format(key=api_key)) for name, value in headers])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ambiguous_credentials"
    assert api_key not in response.text
    assert_private_headers(response)


@respx.mock
@pytest.mark.parametrize("credentials", [{"authorization": "Basic invalid"}, {"authorization": ""}, {"x-api-key": ""}])
def test_malformed_credentials_do_not_fall_back_to_a_cookie(dp_app, api_key, credentials):
    mock_control_plane()
    with TestClient(dp_app) as client:
        client.cookies.set("tokkeeper_playground", api_key)
        response = client.get(
            "/inf/v1/models",
            headers={**credentials, "x-requested-with": "console", "sec-fetch-site": "same-origin"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


@respx.mock
@pytest.mark.parametrize("stream", [False, True])
def test_request_id_matches_response_and_usage_accounting(dp_app, api_key, tmp_path, http_client, stream):
    mock_control_plane()
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=TEXT_LOG) if stream else httpx.Response(200, json=TEXT_NONSTREAM)
    )
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"authorization": f"Bearer {api_key}", "x-request-id": "caller-controlled-id"},
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
        assert {chunk["id"] for chunk in chunks} == {"chatcmpl-9"}
    else:
        assert_private_headers(response)
        assert response.json()["id"] == "chatcmpl-9"
        assert "x-accel-buffering" not in response.headers
    outbox = make_outbox(tmp_path, http_client)
    events = outbox.next_batch(10)
    outbox.close()
    assert len(events) == 1
    assert events[0].request_id == request_id


@respx.mock
def test_policy_denials_have_the_same_request_id_as_the_usage_event(dp_app, api_key, tmp_path, http_client):
    mock_control_plane()
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"authorization": f"Bearer {api_key}"},
            json={"model": "unknown", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 404
    assert_private_headers(response)
    outbox = make_outbox(tmp_path, http_client)
    events = outbox.next_batch(10)
    outbox.close()
    assert events[0].request_id == UUID(response.headers["x-request-id"])


@respx.mock
def test_unexpected_errors_still_have_private_headers(dp_app, api_key):
    mock_control_plane()
    respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=RuntimeError("private internal detail"))
    with TestClient(dp_app, raise_server_exceptions=False) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 500
    assert_private_headers(response)
    assert "private internal detail" not in response.text


@respx.mock
def test_each_request_gets_a_distinct_gateway_id(dp_app, api_key):
    mock_control_plane()
    with TestClient(dp_app) as client:
        headers = {"authorization": f"Bearer {api_key}", "x-request-id": "same-caller-id"}
        first = client.get("/inf/v1/models", headers=headers)
        second = client.get("/inf/v1/models", headers=headers)
    assert UUID(first.headers["x-request-id"]).version == UUID(second.headers["x-request-id"]).version == 7
    assert first.headers["x-request-id"] != second.headers["x-request-id"]
