from __future__ import annotations

import pytest

from data_plane.canonical import CanonicalMessage, ReasoningPart, TextPart
from data_plane.formats.openai_responses import input_of, messages_of

SPELLINGS = [
    (
        "typed input parts",
        [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
        [("user", "hi")],
    ),
    (
        "assistant history as a bare string, the only form Responses takes for it",
        [{"type": "message", "role": "assistant", "content": "Paris"}],
        [("assistant", "Paris")],
    ),
    (
        "user text as a bare string",
        [{"type": "message", "role": "user", "content": "hi"}],
        [("user", "hi")],
    ),
    (
        "no type field, which EasyInputMessage makes optional and the SDKs omit",
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Paris"}],
        [("user", "hi"), ("assistant", "Paris")],
    ),
    (
        "developer role, which canonical folds into system",
        [{"role": "developer", "content": "be terse"}],
        [("system", "be terse")],
    ),
    (
        "assistant echoed back in the output spelling",
        [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Paris"}]}],
        [("assistant", "Paris")],
    ),
]


def _said(messages: list[CanonicalMessage]) -> list[tuple[str, str]]:
    return [(m.role, "".join(p.text for p in m.content if isinstance(p, TextPart))) for m in messages]


@pytest.mark.parametrize(("items", "expected"), [(i, e) for _, i, e in SPELLINGS], ids=[n for n, _, _ in SPELLINGS])
def test_every_documented_input_spelling_survives_the_read(items, expected):
    assert _said(messages_of(items)) == expected


def test_a_conversation_read_then_rewritten_keeps_every_turn():
    original = [
        {"role": "user", "content": "What is the capital of France?"},
        {"role": "assistant", "content": "Paris"},
        {"role": "user", "content": "And of Spain?"},
    ]
    assert _said(messages_of(input_of(messages_of(original)))) == [
        ("user", "What is the capital of France?"),
        ("assistant", "Paris"),
        ("user", "And of Spain?"),
    ]


def test_encrypted_reasoning_survives_a_follow_up_turn():
    original = [{"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"}]
    (message,) = messages_of(original)
    (reasoning,) = message.content
    assert isinstance(reasoning, ReasoningPart)
    assert (reasoning.id, reasoning.data) == ("rs_1", "opaque")
    assert input_of([message]) == original
