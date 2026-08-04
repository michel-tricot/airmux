from __future__ import annotations

import json

import httpx
import respx
from starlette.testclient import TestClient

from data_plane.app import app
from data_plane.outbox import SqliteOutbox


def _recorded(tmp_path):
    outbox = SqliteOutbox(cache_dir=tmp_path, control_plane_url=None, control_plane_token=None, flush_interval_s=5.0)
    events = outbox._read_batch(10)
    outbox.close()
    return events


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
    assert body["usage"] == {"input_tokens": 5, "output_tokens": 2, "cache_read_tokens": 0, "cache_write_tokens": 0, "estimated": False}
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


@respx.mock
def test_policy_denial_is_metered(token, tmp_path):
    with TestClient(app) as client:
        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "ghost", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 404  # unknown model
    events = _recorded(tmp_path)
    assert [(e.status, e.model_id, e.key_id) for e in events] == [("denied", "ghost", "k-dev")]


@respx.mock
def test_upstream_timeout_is_metered_as_timeout(token, tmp_path):
    respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=httpx.ReadTimeout("timed out"))
    with TestClient(app) as client:
        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 504
    events = _recorded(tmp_path)
    assert [e.status for e in events] == ["timeout"]
