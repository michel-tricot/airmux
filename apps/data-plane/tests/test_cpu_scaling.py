from __future__ import annotations

import statistics
import time
import tracemalloc

import pytest
from conftest import CTX, MODEL, make_credential
from test_adapter_streaming import CASES, KINDS, _adapter

from airmux_runtime.secrets import MemoryStoreConfig, Secret
from data_plane.canonical import CanonicalRequest, CanonicalToolDef, CanonicalUserMessage
from data_plane.credentials import CredentialResolver
from data_plane.egress.base import RawEvent
from data_plane.metrics import DataPlaneMetrics

pytestmark = pytest.mark.performance


async def test_warm_credential_lookup_cpu_does_not_scale_with_other_credentials():
    store = MemoryStoreConfig().build()
    entry = make_credential()
    await store.put(entry.ref, Secret("cached"))
    metrics = DataPlaneMetrics()
    resolver = CredentialResolver(store, metrics)
    try:
        await resolver.fetch(entry)

        async def measure():
            started = time.thread_time()
            for _ in range(500):
                assert resolver.available((entry,)) == (entry,)
                assert await resolver.fetch(entry) is not None
            return time.thread_time() - started

        small = statistics.median([await measure() for _ in range(3)])
        for index in range(4096):
            credential = make_credential(name=f"credential-{index}")
            await store.put(credential.ref, Secret("other"))
            await resolver.fetch(credential)
        large = statistics.median([await measure() for _ in range(3)])
        assert large < small * 4, (small, large)
    finally:
        metrics.shutdown()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("modality", ["text", "tools"])
def test_stream_accumulation_cpu_scales_with_fragment_count(kind, modality):
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

    def measure(count):
        state = adapter.new_stream_state(CTX)
        for event in events[: 2 if kind == "anthropic" or modality == "tools" else 1]:
            adapter.transform_stream_event(event, state)
        started = time.thread_time()
        for _ in range(count):
            adapter.transform_stream_event(fragment, state)
        final = adapter.finalize(state)
        elapsed = time.thread_time() - started
        part = final.content[0]
        assert part.type in {"text", "tool_call"}
        value = part.arguments if part.type == "tool_call" else part.text
        assert value == "a" * (count * 1024)
        return elapsed

    small = statistics.median(measure(2048) for _ in range(3))
    large = statistics.median(measure(8192) for _ in range(3))
    assert large < small * 8, (small, large)


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
