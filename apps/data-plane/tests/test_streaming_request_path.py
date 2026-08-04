from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, cast

import httpx
import pytest
import respx
from conftest import CTX, TEXT_LOG, make_adapter, sse
from starlette.responses import StreamingResponse
from starlette.testclient import TestClient

from data_plane.app import _stream, app
from data_plane.canonical import CanonicalRequest, UpstreamRequest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

UPSTREAM = UpstreamRequest(method="POST", url="https://api.openai.com/v1/chat/completions", headers={}, body=b"{}")


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
    text_body = body.decode()
    events = [json.loads(line[6:]) for line in text_body.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
    text = "".join(e["delta"]["text"] for e in events if e.get("delta", {}).get("type") == "text")
    assert text == "héllo \U0001f30d world"
    assert events[-1]["usage"] == {"input_tokens": 5, "output_tokens": 7, "estimated": False}
    assert text_body.rstrip().endswith("data: [DONE]")


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


def _body_gen(response: object) -> AsyncGenerator[bytes]:
    assert isinstance(response, StreamingResponse)
    return cast("AsyncGenerator[bytes]", response.body_iterator)


@respx.mock
async def test_cancellation_records_partial_usage(caplog):
    caplog.set_level(logging.INFO, logger="data_plane")
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=TEXT_LOG))
    iterator = _body_gen(await _stream(make_adapter(), CTX, UPSTREAM))
    first = await anext(iterator)
    assert first.startswith(b"data: ")
    with pytest.raises(asyncio.CancelledError):
        await iterator.athrow(asyncio.CancelledError())
    cancelled = [r.message for r in caplog.records if "status=cancelled" in r.message]
    assert len(cancelled) == 1
    assert "estimated=True" in cancelled[0]


@respx.mock
async def test_cancellation_estimates_partial_tokens(caplog):
    caplog.set_level(logging.INFO, logger="data_plane")
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=TEXT_LOG))
    req = CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "count to three"}], stream=True)
    iterator = _body_gen(await _stream(make_adapter(), CTX, UPSTREAM, req))
    await anext(iterator)
    await anext(iterator)
    with pytest.raises(asyncio.CancelledError):
        await iterator.athrow(asyncio.CancelledError())
    (record,) = [r.message for r in caplog.records if "status=cancelled" in r.message]
    assert "estimated=True" in record
    assert "input_tokens=0" not in record
    assert "output_tokens=0" not in record
    assert "cost_usd=0.000000" not in record


@respx.mock
async def test_mid_stream_error_event_becomes_sse_error(caplog):
    caplog.set_level(logging.INFO, logger="data_plane")
    hi = {"id": "cmpl-9", "model": "gpt-real", "choices": [{"index": 0, "delta": {"content": "héllo "}, "finish_reason": None}]}
    log = sse(hi) + sse({"error": {"code": "overloaded", "message": "try later"}})
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, content=log))
    chunks = [chunk async for chunk in _body_gen(await _stream(make_adapter(), CTX, UPSTREAM))]
    assert any(b'"code": "overloaded"' in c for c in chunks)
    assert any("status=upstream_error" in r.message for r in caplog.records)


async def test_error_body_read_failure_closes_upstream_and_maps(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="data_plane")

    class FakeResp:
        is_error = True

        async def aread(self):
            msg = "connection reset while reading error body"
            raise httpx.ReadError(msg)

    class FakeStreamCM:
        def __init__(self):
            self.exited = False

        async def __aenter__(self):
            return FakeResp()

        async def __aexit__(self, *args):
            self.exited = True

    cm = FakeStreamCM()

    class FakeClient:
        def stream(self, *args, **kwargs):
            return cm

    monkeypatch.setattr("data_plane.app.client", FakeClient())
    response = await _stream(make_adapter(), CTX, UPSTREAM)
    assert cm.exited
    assert response.status_code == 502
    assert any("status=upstream_error" in r.message for r in caplog.records)
