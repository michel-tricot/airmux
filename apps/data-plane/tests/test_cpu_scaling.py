from __future__ import annotations

import statistics
import tracemalloc

import pytest
from conftest import CTX, MODEL, make_credential
from test_adapter_streaming import KINDS, _adapter

from airmux_runtime.secrets import MemoryStoreConfig
from data_plane.canonical import CanonicalChunk, CanonicalReasoningDelta, CanonicalRequest, CanonicalToolDef, CanonicalUserMessage
from data_plane.credentials import CredentialResolver
from data_plane.ingress import REGISTRY as INGRESS
from data_plane.metrics import DataPlaneMetrics

pytestmark = pytest.mark.performance


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
