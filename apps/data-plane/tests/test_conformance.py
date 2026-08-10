from __future__ import annotations

import json

import pytest
from conformance import CASES, Case, Modality, expected_text, make_ctx

from contract import Secret
from data_plane.adapters import REGISTRY
from data_plane.canonical import CanonicalRequest, UpstreamStreamError


def _drain_error(adapter, state, raw: bytes) -> None:
    for ev in adapter.frame(raw, state):
        adapter.transform_stream_event(ev, state)


def _fold(case: Case, raw: bytes, chunk_size: int):
    adapter = case.adapter()
    state = adapter.new_stream_state(case.ctx)
    chunks = []
    for start in range(0, len(raw), chunk_size):
        for ev in adapter.frame(raw[start : start + chunk_size], state):
            chunks.extend(adapter.transform_stream_event(ev, state))
    return chunks, adapter.finalize(state)


def _modalities(case: Case) -> list[Modality]:
    return [case.text, case.tool, case.reasoning]


def _case_modality_ids():
    return [f"{case.kind}-{name}" for case in CASES for name in ("text", "tool", "reasoning")]


def _case_modality_params():
    return [(case, m) for case in CASES for m in _modalities(case)]


@pytest.mark.parametrize(("case", "modality"), _case_modality_params(), ids=_case_modality_ids())
@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 64])
def test_fold_is_invariant_under_adversarial_splits(case: Case, modality: Modality, chunk_size: int):
    log = case.encode(modality.events)
    _, response = _fold(case, log, chunk_size)
    assert response == _fold(case, log, len(log))[1]


@pytest.mark.parametrize(("case", "modality"), _case_modality_params(), ids=_case_modality_ids())
def test_stream_and_nonstream_agree(case: Case, modality: Modality):
    _, streamed = _fold(case, case.encode(modality.events), 7)
    direct = case.adapter().transform_response(json.dumps(modality.nonstream).encode(), case.ctx)
    assert streamed == direct


@pytest.mark.parametrize(("case", "modality"), _case_modality_params(), ids=_case_modality_ids())
def test_streamed_text_matches_final(case: Case, modality: Modality):
    chunks, _ = _fold(case, case.encode(modality.events), 3)
    streamed = "".join(c.delta["text"] for c in chunks if c.delta.get("type") == "text")
    assert streamed == expected_text(case.adapter().transform_response(json.dumps(modality.nonstream).encode(), case.ctx).content)


@pytest.mark.parametrize("case", CASES, ids=[c.kind for c in CASES])
def test_finalize_is_valid_at_every_prefix(case: Case):
    events = case.text.events
    for cut in range(len(events) + 1):
        _, response = _fold(case, case.encode(events[:cut]), 5)
        assert response.model == case.ctx.model.model_id
        assert isinstance(response.usage.input_tokens, int)


@pytest.mark.parametrize("case", CASES, ids=[c.kind for c in CASES])
def test_mid_stream_error_raises_and_maps(case: Case):
    adapter = case.adapter()
    state = adapter.new_stream_state(case.ctx)
    with pytest.raises(UpstreamStreamError) as excinfo:
        _drain_error(adapter, state, case.error_log)
    err = adapter.map_error(excinfo.value)
    assert err.status == 502
    assert err.code == "overloaded" if case.kind == "openai_compatible" else err.code == "overloaded_error"
    partial = adapter.finalize(state)
    assert partial.content == [{"type": "text", "text": "hi"}]


@pytest.mark.parametrize("case", CASES, ids=[c.kind for c in CASES])
def test_tool_arguments_are_valid_json(case: Case):
    _, response = _fold(case, case.encode(case.tool.events), 3)
    (tool,) = response.content
    assert tool["type"] == "tool_call"
    assert json.loads(tool["function"]["arguments"]) == {"city": "Paris"}


def test_anthropic_request_uses_native_shape():
    adapter = REGISTRY["anthropic"](make_ctx("anthropic").provider, Secret("sk-ant-test"))
    req = CanonicalRequest(
        model="claude",
        messages=[{"role": "system", "content": "be terse"}, {"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "f", "description": "d", "parameters": {"type": "object"}}}],
        max_tokens=100,
        stream=True,
    )
    up = adapter.transform_request(req, make_ctx("anthropic").model)
    body = json.loads(up.body)
    assert up.url.endswith("/messages")
    assert up.headers["x-api-key"] == "sk-ant-test"
    assert up.headers["anthropic-version"]
    assert body["system"] == "be terse"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert body["max_tokens"] == 100
    assert body["tools"] == [{"name": "f", "description": "d", "input_schema": {"type": "object"}}]
    assert body["stream"] is True


def test_openai_usage_captures_cached_tokens():
    adapter = REGISTRY["openai_compatible"](make_ctx("openai_compatible").provider, Secret("sk-test"))
    reply = json.dumps(
        {
            "id": "c",
            "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3016, "completion_tokens": 4, "prompt_tokens_details": {"cached_tokens": 2944}},
        }
    ).encode()
    usage = adapter.transform_response(reply, make_ctx("openai_compatible")).usage
    assert usage.input_tokens == 3016  # prompt_tokens already includes cached
    assert usage.cache_read_tokens == 2944
