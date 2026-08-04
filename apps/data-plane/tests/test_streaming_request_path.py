from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from starlette.responses import StreamingResponse
from starlette.testclient import TestClient
from test_streaming_fold import CTX, PROVIDER, TEXT_LOG, make_adapter

from contract import BundleV1, Catalog, KeyEntry, ModelEntry, mint_api_token, sign_bundle
from data_plane.app import _stream, app
from data_plane.canonical import UpstreamRequest

NOW = datetime.now(tz=UTC)

UPSTREAM = UpstreamRequest(method="POST", url="https://api.openai.com/v1/chat/completions", headers={}, body=b"{}")


@pytest.fixture
def token(tmp_path, monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    token_key = Ed25519PrivateKey.generate()
    bundle = BundleV1(
        bundle_id=uuid4(),
        org_id="org-dev",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        keys=[KeyEntry(key_id="k-dev", org_id="org-dev", allowed_models=["*"])],
        revocations=[],
        catalog=Catalog(
            providers=[PROVIDER],
            models=[
                ModelEntry(
                    model_id="gpt-test",
                    provider_id="p1",
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

    def b64(key):
        return base64.b64encode(key.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)).decode()

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GW_CONFIG", raising=False)
    config = (
        f'data_plane:\n  bundle:\n    public_key: "{b64(private_key)}"\n    cache_dir: {tmp_path}\n'
        f'  auth:\n    token_public_key: "{b64(token_key)}"\n'
    )
    (tmp_path / "airllm.yml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    return mint_api_token("k-dev", "org-dev", token_key, NOW)


@respx.mock
def test_streaming_end_to_end(token):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=TEXT_LOG))
    with (
        TestClient(app) as client,
        client.stream(
            "POST",
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        ) as r,
    ):
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = b"".join(r.iter_bytes())
    events = [json.loads(line[6:]) for line in body.decode().splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
    text = "".join(e["delta"]["text"] for e in events if e.get("delta", {}).get("type") == "text")
    assert text == "héllo \U0001f30d world"
    assert events[-1]["usage"] == {"input_tokens": 5, "output_tokens": 7, "estimated": False}
    assert body.decode().splitlines()[-2] == "data: [DONE]" or body.decode().rstrip().endswith("data: [DONE]")


@respx.mock
def test_streaming_upstream_error_status_passes_through(token):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(429, json={"error": {"code": "rate_limited"}}))
    with TestClient(app) as client:
        r = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )
    assert r.status_code == 429


@respx.mock
async def test_cancellation_records_partial_usage(caplog):
    caplog.set_level(logging.INFO, logger="data_plane")
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=TEXT_LOG))
    response = await _stream(make_adapter(), CTX, UPSTREAM)
    assert isinstance(response, StreamingResponse)
    iterator = response.body_iterator
    first = await anext(iterator)
    assert first.startswith(b"data: ")
    with pytest.raises(asyncio.CancelledError):
        await iterator.athrow(asyncio.CancelledError())
    cancelled = [r.message for r in caplog.records if "status=cancelled" in r.message]
    assert len(cancelled) == 1
    assert "estimated=True" in cancelled[0]


@respx.mock
async def test_mid_stream_error_event_becomes_sse_error(caplog):
    caplog.set_level(logging.INFO, logger="data_plane")
    log = TEXT_LOG.split(b"data: [DONE]")[0][: TEXT_LOG.index(b'data: {"id": "chatcmpl-9", "model": "gpt-real", "choices": []')]
    log += b'data: {"error": {"code": "overloaded", "message": "try later"}}\n\n'
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=log))
    response = await _stream(make_adapter(), CTX, UPSTREAM)
    assert isinstance(response, StreamingResponse)
    chunks = [chunk async for chunk in response.body_iterator]
    assert any(b'"code": "overloaded"' in c for c in chunks)
    assert any("status=upstream_error" in r.message for r in caplog.records)
