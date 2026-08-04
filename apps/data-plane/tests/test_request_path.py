from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.testclient import TestClient

from contract import BundleV1, Catalog, KeyEntry, ModelEntry, ProviderEntry, mint_api_token, sign_bundle
from data_plane.app import app

NOW = datetime.now(tz=UTC)

OPENAI_RESPONSE = {
    "id": "chatcmpl-123",
    "model": "gpt-real",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello there"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
}


@pytest.fixture
def token(tmp_path, monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    bundle = BundleV1(
        bundle_id=uuid4(),
        org_id="org-dev",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        keys=[KeyEntry(key_id="k-dev", org_id="org-dev", allowed_models=["*"])],
        revocations=[],
        catalog=Catalog(
            providers=[
                ProviderEntry(
                    provider_id="openai", kind="openai_compatible", base_url="https://api.openai.com/v1", credential_ref="env:OPENAI_API_KEY"
                )
            ],
            models=[
                ModelEntry(
                    model_id="gpt-test",
                    provider_id="openai",
                    upstream_model="gpt-real",
                    input_price_per_mtok=1.0,
                    output_price_per_mtok=2.0,
                    context_window=128000,
                    capabilities=["streaming"],
                )
            ],
        ),
    )
    (tmp_path / "bundle.json").write_text(sign_bundle(bundle, private_key, "k1").model_dump_json(), encoding="utf-8")
    public_b64 = base64.b64encode(
        private_key.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    ).decode("ascii")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GW_CONFIG", raising=False)
    (tmp_path / "airllm.yml").write_text(f'data_plane:\n  bundle:\n    public_key: "{public_b64}"\n    cache_dir: {tmp_path}\n', encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    return mint_api_token("k-dev", "org-dev", private_key, NOW)


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
