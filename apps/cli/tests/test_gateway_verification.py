from __future__ import annotations

import httpx
import pytest

from cli.auth import verify_gateway


@pytest.mark.parametrize(
    ("responses", "expected"),
    [
        ([(401, "invalid_token"), (200, "")], ""),
        ([(401, "invalid_token")] * 20, "HTTP 401: invalid_token"),
        ([(502, "provider_error")], "HTTP 502: provider_error"),
        ([(401, "provider_auth")], "HTTP 401: provider_auth"),
    ],
)
def test_verification_waits_for_a_new_key_but_does_not_retry_provider_requests(monkeypatch, responses, expected):
    pending = iter(responses)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/readyz":
            return httpx.Response(200)
        status, code = next(pending)
        return httpx.Response(status, json={"error": {"code": code}})

    client = httpx.Client(base_url="http://gateway", transport=httpx.MockTransport(respond))
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr("cli.auth.time.sleep", lambda _seconds: None)

    assert verify_gateway("http://gateway", "new-key", "test-model") == expected
