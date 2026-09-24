from __future__ import annotations

import json

import httpx
import pytest

from cli.auth import verify_gateway


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        ([(401, "invalid_token"), (200, "")], ""),
        ([(402, "credential_unavailable"), (200, "")], ""),
        ([(401, "invalid_token")] * 20, "HTTP 401: invalid_token"),
        ([(402, "credential_unavailable")] * 20, "HTTP 402: credential_unavailable"),
        ([(502, "provider_error")], "HTTP 502: provider_error"),
        ([(401, "provider_auth")], "HTTP 401: provider_auth"),
    ],
)
def test_verification_waits_for_bundle_inputs_but_does_not_retry_provider_requests(monkeypatch, responses, expected):
    pending = iter(responses)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/readyz":
            return httpx.Response(200)
        assert json.loads(request.content) == {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Say hello in one word."}],
            "stream": False,
        }
        status, code = next(pending)
        return httpx.Response(status, json={"error": {"code": code}})

    client = httpx.Client(base_url="http://gateway", transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr("cli.auth.time.sleep", lambda _seconds: None)

    assert verify_gateway("http://gateway", "new-key", "test-model") == expected
