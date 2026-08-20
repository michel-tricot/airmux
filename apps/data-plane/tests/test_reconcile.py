from __future__ import annotations

from conftest import MODEL, PROVIDER

from data_plane.canonical import CanonicalRequest, ReasoningConfig
from data_plane.profiles import compile_profile
from data_plane.reconcile import reconcile


def _request(**extras) -> CanonicalRequest:
    return CanonicalRequest.model_validate({"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}], **extras})


def _closed(**overrides):
    return PROVIDER.model_copy(update={"params_closed": True, **overrides})


def test_an_open_schema_forwards_extras_without_an_adjustment():
    req, adjustments = reconcile(_request(frequency_penalty=0.5, top_k=40), MODEL, compile_profile(PROVIDER))
    assert req.extra == {"frequency_penalty": 0.5, "top_k": 40}
    assert adjustments == []


def test_a_closed_schema_drops_undeclared_extras_with_the_reason():
    req, adjustments = reconcile(_request(top_k=40), MODEL, compile_profile(_closed()))
    assert req.extra == {}
    assert [(a.param, a.action) for a in adjustments] == [("top_k", "dropped")]
    assert PROVIDER.provider_id in adjustments[0].detail


def test_a_closed_schema_forwards_its_declared_params():
    req, adjustments = reconcile(_request(top_k=40, min_p=0.1), MODEL, compile_profile(_closed(accepted_params=["top_k"])))
    assert req.extra == {"top_k": 40}
    assert [a.param for a in adjustments] == ["min_p"]


def test_n_is_held_by_the_gateway_everywhere():
    """n asks for a choices axis the locked response does not have; honoring it would discard output."""
    req, adjustments = reconcile(_request(n=3), MODEL, compile_profile(PROVIDER))
    assert req.extra == {}
    assert [(a.param, a.action) for a in adjustments] == [("n", "dropped")]


def test_without_alias_knowledge_an_unknown_spelling_forwards():
    """The gateway cannot know max_completion_tokens is a spelling of max_tokens unless the
    provider profile says so; without that fact it is an ordinary extra on an open schema."""
    req, adjustments = reconcile(_request(max_tokens=100, max_completion_tokens=999), MODEL, compile_profile(PROVIDER))
    assert req.extra == {"max_completion_tokens": 999}
    assert adjustments == []


def test_an_extra_colliding_with_an_alias_spelling_drops():
    """The provider spells max_tokens as max_completion_tokens; an extra by that name would collide
    with the rendered core field after aliasing."""
    provider = PROVIDER.model_copy(update={"param_aliases": {"max_tokens": "max_completion_tokens"}})
    req, adjustments = reconcile(_request(max_tokens=100, max_completion_tokens=999), MODEL, compile_profile(provider))
    assert req.extra == {}
    assert [a.param for a in adjustments] == ["max_completion_tokens"]
    assert "max_tokens" in adjustments[0].detail


def test_the_clamp_still_reports():
    model = MODEL.model_copy(update={"max_output_tokens": 50})
    req, adjustments = reconcile(_request(max_tokens=100), model, compile_profile(PROVIDER))
    assert req.max_tokens == 50
    assert [(a.param, a.action) for a in adjustments] == [("max_tokens", "clamped")]


def test_an_unsupported_model_parameter_is_dropped_with_an_adjustment():
    model = MODEL.model_copy(update={"parameter_support": {"temperature": "unsupported"}})
    req, adjustments = reconcile(_request(temperature=0.7), model, compile_profile(PROVIDER))
    assert req.temperature is None
    assert [(a.param, a.action) for a in adjustments] == [("temperature", "dropped")]
    assert model.model_id in adjustments[0].detail


def test_unknown_model_parameter_support_preserves_the_parameter():
    req, adjustments = reconcile(_request(temperature=0.7), MODEL, compile_profile(PROVIDER))
    assert req.temperature == 0.7
    assert adjustments == []


def test_reasoning_effort_uses_its_parameter_support_entry():
    model = MODEL.model_copy(update={"parameter_support": {"reasoning_effort": "unsupported"}})
    req, adjustments = reconcile(_request(reasoning={"effort": "high"}), model, compile_profile(PROVIDER))
    assert req.reasoning == ReasoningConfig()
    assert [(a.param, a.action) for a in adjustments] == [("reasoning_effort", "dropped")]
