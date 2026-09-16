from __future__ import annotations

import json

import httpx
import pytest
import respx
from conftest import PROVIDER, mock_control_plane
from starlette.testclient import TestClient

from airmux_runtime.secrets import Secret
from data_plane.egress import REGISTRY
from data_plane.egress.base import ProviderDiagnostic, UpstreamResponseError, UpstreamStreamError
from data_plane.egress.openai_compatible import OpenAICompatibleAdapter

SENTINEL = "synthetic-provider-secret-20260911"


class FutureOpenAIAdapter(OpenAICompatibleAdapter):
    def parse_error(self, error: UpstreamResponseError) -> ProviderDiagnostic | None:
        return ProviderDiagnostic(code=SENTINEL, message=f"future adapter rejected {error.status}: {SENTINEL}")


def _error_body(kind: str) -> bytes:
    if kind == "anthropic":
        value = {"type": "error", "error": {"type": SENTINEL, "message": f"invalid model for {SENTINEL}"}}
    elif kind == "openai_responses":
        value = {"type": "error", "error": {"type": "invalid_request_error", "code": SENTINEL, "message": f"invalid model for {SENTINEL}"}}
    else:
        value = {"error": {"code": SENTINEL, "message": f"invalid model for {SENTINEL}"}}
    return json.dumps(value).encode()


@pytest.mark.parametrize("status", [400, 401, 403, 502])
@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_parsed_provider_errors_preserve_diagnostics_after_credential_redaction(kind, status):
    adapter = REGISTRY[kind](PROVIDER.model_copy(update={"kind": kind}), Secret(SENTINEL))
    rendered = adapter.map_error(UpstreamResponseError(status, _error_body(kind)))
    assert rendered.status == status
    assert rendered.code == "[REDACTED]"
    assert rendered.message == "invalid model for [REDACTED]"


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_stream_errors_preserve_diagnostics_after_credential_redaction(kind):
    adapter = REGISTRY[kind](PROVIDER.model_copy(update={"kind": kind}), Secret(SENTINEL))
    rendered = adapter.map_error(UpstreamStreamError(SENTINEL, SENTINEL))
    assert rendered.code == "[REDACTED]"
    assert rendered.message == "[REDACTED]"


def test_new_adapter_error_parsers_inherit_redaction():
    adapter = FutureOpenAIAdapter(PROVIDER, Secret(SENTINEL))
    rendered = adapter.map_error(UpstreamResponseError(422, b"future error"))
    assert rendered.model_dump() == {"status": 422, "code": "[REDACTED]", "message": "future adapter rejected 422: [REDACTED]"}


@respx.mock
def test_provider_echo_of_a_non_header_shaped_credential_is_redacted(api_key, dp_app, monkeypatch, caplog):
    credential = SENTINEL + " value"
    monkeypatch.setenv("P1_API_KEY", credential)
    mock_control_plane()
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(400, json={"error": {"code": credential, "message": f"invalid credential {credential}"}})
    )
    with TestClient(dp_app) as client:
        response = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert response.status_code == 400
    assert response.json()["error"] == {"code": "[REDACTED]", "message": "invalid credential [REDACTED]"}
    assert credential not in response.text
    assert credential not in caplog.text
