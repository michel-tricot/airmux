from __future__ import annotations

import json

import httpx
import respx
from starlette.testclient import TestClient

from data_plane.app import app

OPENAI_RESPONSE = {
    "id": "chatcmpl-123",
    "model": "gpt-real",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello there"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
}


@respx.mock
def test_chat_completion_end_to_end(token):
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=OPENAI_RESPONSE))
    with TestClient(app) as client:
        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "say hi"}]},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == [{"type": "text", "text": "hello there"}]
    assert body["usage"] == {"input_tokens": 5, "output_tokens": 2, "estimated": False}
    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "gpt-real"
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-test-not-real"


@respx.mock
def test_missing_token_rejected(token):
    with TestClient(app) as client:
        r = client.post("/v1/chat/completions", json={"model": "gpt-test", "messages": []})
    assert r.status_code == 401


@respx.mock
def test_upstream_error_passed_through(token):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(429, json={"error": {"code": "rate_limited"}}))
    with TestClient(app) as client:
        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 429
