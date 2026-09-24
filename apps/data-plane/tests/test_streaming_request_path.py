from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from conftest import CTX, ORG, PROVIDER, TEXT_LOG, WORKSPACE, delta_event, make_outbox, mock_control_plane, sse
from starlette.requests import ClientDisconnect
from starlette.responses import Response, StreamingResponse
from starlette.testclient import TestClient
from test_adapter_streaming import CASES, ERROR_LOGS

from airmux_runtime.secrets import Secret
from contract import TokenUsageSource, uuid7
from data_plane.canonical import CanonicalRequest
from data_plane.egress import REGISTRY as EGRESS
from data_plane.egress.base import Ctx, UpstreamRequest
from data_plane.ingress import REGISTRY as INGRESS
from data_plane.metrics import DataPlaneMetrics
from data_plane.streaming import StreamSession

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from data_plane.outbox import SqliteOutbox

UPSTREAM = UpstreamRequest(method="POST", url="https://api.openai.com/v1/chat/completions", headers={}, body=b"{}")
REQUEST = CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "hi"}], stream=True)


@pytest.fixture
async def metering(tmp_path, http_client) -> AsyncGenerator[tuple[Ctx, SqliteOutbox]]:
    outbox = make_outbox(tmp_path, http_client)
    ctx = replace(
        CTX,
        request_id=uuid7(),
        org_id=ORG,
        workspace_id=WORKSPACE,
        key_id=str(uuid7()),
        credential_id=uuid7(),
        credential_scope="workspace",
        bundle_id=uuid7(),
    )
    yield ctx, outbox
    await outbox.close()


async def _event(outbox: SqliteOutbox):
    (event,) = await outbox.next_batch(10)
    return event


def test_streaming_end_to_end(http_mock, api_key, dp_app):
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, body=TEXT_LOG, repeat=True)
    mock_control_plane(http_mock)
    with (
        TestClient(dp_app) as client,
        client.stream(
            "POST",
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        ) as r,
    ):
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = b"".join(r.iter_bytes())
    text_body = body.decode()
    events = [json.loads(line[6:]) for line in text_body.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
    text = "".join(e["choices"][0]["delta"].get("content", "") for e in events if e["choices"])
    assert text == "héllo \U0001f30d world"
    assert events[-1]["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 7,
        "total_tokens": 12,
        "prompt_tokens_details": {"cached_tokens": 0},
    }
    assert text_body.rstrip().endswith("data: [DONE]")


def test_streaming_upstream_error_status_passes_through(http_mock, api_key, dp_app):
    http_mock.post("https://api.openai.com/v1/chat/completions", status=429, payload={"error": {"code": "rate_limited"}}, repeat=True)
    mock_control_plane(http_mock)
    with TestClient(dp_app) as client:
        r = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )
    assert r.status_code == 429


def _payloads(chunks):
    return [json.loads(line[6:]) for line in b"".join(chunks).splitlines() if line.startswith(b"data: ") and line != b"data: [DONE]"]


def _body_gen(response: object) -> AsyncGenerator[bytes]:
    assert isinstance(response, StreamingResponse)
    return cast("AsyncGenerator[bytes]", response.body_iterator)


async def _open_stream(
    metering: tuple[Ctx, SqliteOutbox],
    http_client: aiohttp.ClientSession,
    metrics: DataPlaneMetrics | None = None,
    *,
    protocols: tuple[str, str] = ("openai_compatible", "openai_chat_completions"),
    upstream: UpstreamRequest = UPSTREAM,
) -> Response:
    ctx, outbox = metering
    kind, dialect = protocols
    with outbox.reserve() as reservation:
        session = StreamSession(
            adapter=EGRESS[kind](PROVIDER.model_copy(update={"kind": kind}), Secret("sk-test")),
            ingress=INGRESS[dialect],
            ctx=ctx,
            request=REQUEST,
            adjustments=(),
            reservation=reservation,
            http_client=http_client,
            metrics=metrics or DataPlaneMetrics(),
            egress_kind=kind,
            attempt_started_at=time.monotonic(),
        )
        return await session.open(upstream)


@pytest.mark.parametrize("complete", [False, True])
async def test_cancellation_records_available_provider_usage(complete, http_mock, metering, http_client):
    _, outbox = metering
    payload = TEXT_LOG if complete else sse(delta_event({"content": "héllo "}))
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, body=payload, repeat=True)
    iterator = _body_gen(await _open_stream(metering, http_client))
    await anext(iterator)
    await anext(iterator)
    with pytest.raises(asyncio.CancelledError):
        await iterator.athrow(asyncio.CancelledError())
    event = await _event(outbox)
    assert event.status == "cancelled"
    assert event.input_tokens > 0
    assert event.output_tokens > 0
    assert event.cost_usd > 0
    assert event.token_usage_source == (TokenUsageSource.PROVIDER if complete else TokenUsageSource.ESTIMATED)
    if complete:
        assert (event.input_tokens, event.output_tokens) == (5, 7)


async def test_disconnect_before_first_body_releases_stream_resources(monkeypatch, metering, http_client):
    _, outbox = metering

    class FakeResponse:
        status = 200

    class FakeStream:
        exited = False

        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *_args):
            self.exited = True

    stream = FakeStream()
    monkeypatch.setattr(http_client, "request", lambda *_args, **_kwargs: stream)
    response = await _open_stream(metering, http_client)

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_message):
        raise OSError

    with pytest.raises(ClientDisconnect):
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)

    assert stream.exited
    assert (await outbox.stats())["reserved"] == 0
    assert (await _event(outbox)).status == "cancelled"


async def test_mid_stream_error_event_becomes_sse_error(http_mock, metering, http_client):
    _, outbox = metering
    metrics = DataPlaneMetrics()
    hi = {"id": "cmpl-9", "model": "gpt-real", "choices": [{"index": 0, "delta": {"content": "héllo "}, "finish_reason": None}]}
    log = sse(hi) + sse({"error": {"code": "overloaded", "message": "try later"}})
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, body=log, repeat=True)
    chunks = [chunk async for chunk in _body_gen(await _open_stream(metering, http_client, metrics))]
    assert any(event.get("error", {}).get("code") == "overloaded" for event in _payloads(chunks))
    assert (await _event(outbox)).status == "upstream_error"
    assert 'airmux_data_plane_upstream_attempts_total{egress_kind="openai_compatible",outcome="provider_error"} 1.0' in metrics.render().decode()


async def test_stream_ending_before_the_provider_terminal_becomes_sse_error(http_mock, metering, http_client):
    _, outbox = metering
    incomplete = TEXT_LOG.removesuffix(b"data: [DONE]\n\n")
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, body=incomplete, repeat=True)
    chunks = [chunk async for chunk in _body_gen(await _open_stream(metering, http_client))]
    assert any(event.get("error", {}).get("code") == "invalid_upstream_response" for event in _payloads(chunks))
    assert (await _event(outbox)).status == "upstream_error"


async def test_malformed_stream_event_becomes_sse_error(http_mock, metering, http_client):
    _, outbox = metering
    http_mock.post("https://api.openai.com/v1/chat/completions", status=200, body=b"data: not-json\n\n", repeat=True)
    chunks = [chunk async for chunk in _body_gen(await _open_stream(metering, http_client))]
    assert any(event.get("error", {}).get("code") == "invalid_upstream_response" for event in _payloads(chunks))
    assert (await _event(outbox)).status == "upstream_error"


async def test_error_body_read_failure_closes_upstream_and_propagates(monkeypatch, metering, http_client):
    class FakeResp:
        status = 502

        async def read(self):
            msg = "connection reset while reading error body"
            raise aiohttp.ClientPayloadError(msg)

    class FakeStreamCM:
        def __init__(self):
            self.exited = False

        async def __aenter__(self):
            return FakeResp()

        async def __aexit__(self, *args):
            self.exited = True

    cm = FakeStreamCM()

    class FakeClient:
        def request(self, *args, **kwargs):
            return cm

    monkeypatch.setattr(http_client, "request", FakeClient().request)
    with pytest.raises(aiohttp.ClientPayloadError, match="connection reset"):
        await _open_stream(metering, http_client)
    assert cm.exited


@pytest.fixture(params=[(kind, dialect) for kind in sorted(EGRESS) for dialect in sorted(INGRESS)])
def protocols(request):
    return request.param


@pytest.fixture
def stream_clock(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1_700_000_000)


def _render_frames(kind, dialect, ctx, payload, *, complete=True):
    adapter = EGRESS[kind](PROVIDER.model_copy(update={"kind": kind}), Secret("sk-test"))
    state = adapter.new_stream_state(ctx)
    renderer = INGRESS[dialect].new_stream()
    frames = renderer.start(ctx)
    for event in adapter.frame(payload, state):
        for chunk in adapter.transform_stream_event(event, state):
            frames.extend(renderer.chunk(chunk))
    if complete:
        frames.extend(renderer.closing(adapter.finalize(state), []))
    return frames


@pytest.mark.parametrize("modality", ["text", "tools"])
@pytest.mark.usefixtures("stream_clock")
async def test_available_stream_frames_are_batched_without_changing_bytes(protocols, modality, http_mock, metering, http_client):
    kind, dialect = protocols
    ctx, outbox = metering
    payload = CASES[kind][modality].log
    http_mock.post(UPSTREAM.url, status=200, body=payload)
    expected = _render_frames(kind, dialect, ctx, payload)
    response = await _open_stream(metering, http_client, protocols=protocols)
    batches = [batch async for batch in _body_gen(response)]
    assert b"".join(batches) == b"".join(expected)
    assert len(batches) < len(expected)
    assert (await _event(outbox)).status == "ok"


@pytest.mark.parametrize("failure", ["provider", "malformed"])
@pytest.mark.usefixtures("stream_clock")
async def test_buffered_stream_prefix_precedes_error(protocols, failure, http_mock, metering, http_client):
    kind, dialect = protocols
    ctx, outbox = metering
    prefix = b"\n\n".join(CASES[kind]["text"].log.split(b"\n\n")[:3]) + b"\n\n"
    expected = b"".join(_render_frames(kind, dialect, ctx, prefix, complete=False))
    suffix = ERROR_LOGS[kind] if failure == "provider" else b"data: not-json\n\n"
    http_mock.post(UPSTREAM.url, status=200, body=prefix + suffix)
    response = await _open_stream(metering, http_client, protocols=protocols)
    body = b"".join([batch async for batch in _body_gen(response)])
    assert body.startswith(expected)
    code = b"overloaded" if failure == "provider" else b"invalid_upstream_response"
    assert code in body[len(expected) :]
    assert (await _event(outbox)).status == "upstream_error"


@pytest.mark.parametrize("dialect", sorted(INGRESS))
@pytest.mark.usefixtures("stream_clock")
async def test_large_stream_batches_are_bounded_and_preserve_content(dialect, metering, http_client):
    ctx, outbox = metering
    payload = sse(delta_event({"content": "x" * 1024})) * 512 + sse(delta_event({}, finish="stop")) + b"data: [DONE]\n\n"
    expected = _render_frames("openai_compatible", dialect, ctx, payload)

    async def stream(_request):
        return web.Response(body=payload, content_type="text/event-stream")

    provider = web.Application()
    provider.router.add_post("/", stream)
    async with TestServer(provider) as server:
        response = await _open_stream(
            metering, http_client, protocols=("openai_compatible", dialect), upstream=replace(UPSTREAM, url=str(server.make_url("/")))
        )
        batches = [batch async for batch in _body_gen(response)]
    assert b"".join(batches) == b"".join(expected)
    assert max(map(len, batches)) < 65_536 + max(map(len, expected))
    assert len(batches) < len(expected) // 2
    assert (await _event(outbox)).status == "ok"


@pytest.mark.parametrize("cancel", [False, True])
async def test_stream_prefix_arrives_before_next_provider_read(protocols, cancel, metering, http_client):
    kind, _ = protocols
    _, outbox = metering
    release = asyncio.Event()
    delivered = asyncio.Event()
    payload = CASES[kind]["text"].log
    prefix = b"\n\n".join(payload.split(b"\n\n")[:3]) + b"\n\n"
    received = bytearray()

    async def stream(request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(prefix)
        await release.wait()
        with suppress(ConnectionResetError):
            await response.write(payload[len(prefix) :])
        return response

    async def send(message):
        if message["type"] == "http.response.body":
            received.extend(message["body"])
            if "héllo".encode() in received:
                delivered.set()

    async def receive():
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    provider = web.Application()
    provider.router.add_post("/", stream)
    async with TestServer(provider) as server:
        response = await _open_stream(metering, http_client, protocols=protocols, upstream=replace(UPSTREAM, url=str(server.make_url("/"))))
        task = asyncio.create_task(response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send))
        try:
            await asyncio.wait_for(delivered.wait(), 1)
            assert not release.is_set()
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                release.set()
                await asyncio.wait_for(task, 1)
            event = await _event(outbox)
            assert event.status == ("cancelled" if cancel else "ok")
            assert event.input_tokens > 0
            assert event.output_tokens > 0
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("disconnect", [(version, stage) for version in ("2.3", "2.4") for stage in ("http.response.start", "http.response.body")])
async def test_disconnect_closes_stream_iterator_and_preserves_usage(protocols, disconnect, http_mock, metering, http_client):
    spec_version, disconnect_at = disconnect
    kind, _ = protocols
    _, outbox = metering
    http_mock.post(UPSTREAM.url, status=200, body=CASES[kind]["text"].log)
    response = await _open_stream(metering, http_client, protocols=protocols)
    iterator = _body_gen(response)
    disconnected = asyncio.Event()

    async def receive():
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == disconnect_at:
            if spec_version == "2.4":
                raise OSError
            disconnected.set()
            await asyncio.Event().wait()

    scope = {"type": "http", "asgi": {"spec_version": spec_version}}
    if spec_version == "2.4":
        with pytest.raises(ClientDisconnect):
            await response(scope, receive, send)
    else:
        await asyncio.wait_for(response(scope, receive, send), 1)

    event = await _event(outbox)
    assert event.status == "cancelled"
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)
    assert await _event(outbox) == event
