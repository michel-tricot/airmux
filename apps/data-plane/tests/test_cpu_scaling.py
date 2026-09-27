from __future__ import annotations

import statistics
import sys
import tracemalloc
from types import SimpleNamespace

import pytest
from conftest import CTX, MODEL, make_credential
from test_adapter_streaming import CASES, KINDS, _adapter

from airmux_runtime.secrets import MemoryStoreConfig, Secret
from data_plane.canonical import CanonicalChunk, CanonicalReasoningDelta, CanonicalRequest, CanonicalToolDef, CanonicalUserMessage
from data_plane.credentials import CredentialResolver
from data_plane.egress.base import RawEvent
from data_plane.ingress import REGISTRY as INGRESS
from data_plane.metrics import DataPlaneMetrics

pytestmark = pytest.mark.performance


async def test_warm_credential_lookup_work_does_not_scale_with_other_credentials(monkeypatch):
    monkeypatch.setattr("data_plane.credentials.time", SimpleNamespace(monotonic=lambda: 1.0))
    store = MemoryStoreConfig().build()
    entry = make_credential()
    secret = Secret("cached")
    await store.put(entry.ref, secret)
    metrics = DataPlaneMetrics()
    resolver = CredentialResolver(store, metrics)
    try:
        cached = await resolver.fetch(entry)
        assert cached is not None

        async def measure():
            executed_lines = 0

            def trace(frame, event, arg):
                nonlocal executed_lines
                if event == "line" and frame.f_code.co_filename == CredentialResolver.fetch.__code__.co_filename:
                    executed_lines += 1
                return trace

            previous_trace = sys.gettrace()
            sys.settrace(trace)
            try:
                assert resolver.available((entry,)) == (entry,)
                assert await resolver.fetch(entry) is cached
            finally:
                sys.settrace(previous_trace)
            return executed_lines

        small = await measure()
        for index in range(4096):
            credential = make_credential(name=f"credential-{index}")
            await store.put(credential.ref, Secret("other"))
            await resolver.fetch(credential)
        large = await measure()
        assert 0 < large <= small * 2, (small, large)
    finally:
        metrics.shutdown()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("modality", ["text", "tools"])
@pytest.mark.parametrize("fragment_count", [2048, 8192])
def test_stream_accumulation_does_not_recopy_prior_fragments(kind, modality, fragment_count):
    adapter = _adapter(kind)
    events = list(adapter.frame(CASES[kind][modality].log, adapter.new_stream_state(CTX)))
    fragments = {
        ("anthropic", "text"): b'{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"%s"}}',
        ("anthropic", "tools"): b'{"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"%s"}}',
        ("openai_compatible", "text"): b'{"choices":[{"index":0,"delta":{"content":"%s"}}]}',
        ("openai_compatible", "tools"): b'{"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"%s"}}]}}]}',
        ("openai_responses", "text"): b'{"type":"response.output_text.delta","output_index":0,"delta":"%s"}',
        ("openai_responses", "tools"): b'{"type":"response.function_call_arguments.delta","output_index":0,"delta":"%s"}',
    }
    fragment = RawEvent(data=fragments[kind, modality] % (b"a" * 1024))
    state = adapter.new_stream_state(CTX)
    for event in events[: 2 if kind == "anthropic" or modality == "tools" else 1]:
        adapter.transform_stream_event(event, state)
    for _ in range(fragment_count):
        adapter.transform_stream_event(fragment, state)

    probe_count = 32
    allocated = 0
    tracemalloc.start()
    try:
        for _ in range(probe_count):
            current, _ = tracemalloc.get_traced_memory()
            tracemalloc.reset_peak()
            adapter.transform_stream_event(fragment, state)
            _, peak = tracemalloc.get_traced_memory()
            allocated += peak - current
    finally:
        tracemalloc.stop()
    assert allocated < fragment_count * 16 + probe_count * 16_384, allocated
    final = adapter.finalize(state)
    part = final.content[0]
    assert part.type in {"text", "tool_call"}
    value = part.arguments if part.type == "tool_call" else part.text
    assert value == "a" * ((fragment_count + probe_count) * 1024)


@pytest.mark.parametrize("kind", KINDS)
def test_provider_translation_does_not_duplicate_large_tool_schema_trees(kind):
    parameters = {
        "type": "object",
        "properties": {f"field_{index}": {"type": ["string", "null"], "description": "value " * 8, "default": None} for index in range(64)},
    }
    request = CanonicalRequest(
        model=MODEL.model_id,
        messages=[CanonicalUserMessage(content="hello")],
        tools=[CanonicalToolDef(name=f"tool_{index}", parameters=parameters) for index in range(32)],
        max_output_tokens=64,
    )
    adapter = _adapter(kind)
    adapter.transform_request(request, MODEL)
    tracemalloc.start()
    try:
        upstream = adapter.transform_request(request, MODEL)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < len(upstream.body) * 2, (peak, len(upstream.body))


@pytest.mark.parametrize("dialect", INGRESS)
def test_repeated_reasoning_identity_does_not_allocate_discarded_blocks(dialect):
    stream = INGRESS[dialect].new_stream()
    stream.start(CTX)
    chunk = CanonicalChunk(id="response", delta=CanonicalReasoningDelta(id="reasoning"))
    stream.chunk(chunk)
    if stream.chunk(chunk):
        pytest.skip("This dialect emits repeated reasoning identity updates")
    peaks = []
    for _ in range(5):
        tracemalloc.start()
        try:
            assert stream.chunk(chunk) == []
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        peaks.append(peak)
    assert statistics.median(peaks) < 256, peaks


def test_credentials_without_cooldowns_do_not_allocate_a_candidate_copy():
    entries = tuple(make_credential(name=f"credential-{index}") for index in range(1024))
    metrics = DataPlaneMetrics()
    resolver = CredentialResolver(MemoryStoreConfig().build(), metrics)
    try:
        tracemalloc.start()
        try:
            available = resolver.available(entries)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert available == entries
        assert peak < 1024, peak
    finally:
        metrics.shutdown()
