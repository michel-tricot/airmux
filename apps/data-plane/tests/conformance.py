"""Adapter conformance cases: each adapter contributes wire fixtures, the suite asserts the shared invariants.

An adapter passes M4 by producing a Case here; no per-adapter test suites (see PROTOTYPE.md 6.5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from contract import ModelEntry, ProviderEntry, Secret
from data_plane.adapters import REGISTRY
from data_plane.canonical import Ctx

if TYPE_CHECKING:
    from collections.abc import Callable

    from data_plane.adapters.base import ProviderAdapter


@dataclass
class Modality:
    events: list[dict]  # provider-shaped stream events, in order
    nonstream: dict  # the equivalent non-streaming reply body


@dataclass
class Case:
    kind: str
    ctx: Ctx
    encode: Callable[[list[dict]], bytes]  # provider events -> wire bytes (adapter-specific framing)
    text: Modality
    tool: Modality
    reasoning: Modality
    error_log: bytes  # a partial stream that ends in a provider error event

    def adapter(self) -> ProviderAdapter:
        return REGISTRY[self.kind](_PROVIDERS[self.kind], Secret("sk-test"))


def expected_text(nonstream_content: list[dict]) -> str:
    return "".join(b.get("text", "") for b in nonstream_content if b.get("type") == "text")


_PROVIDERS = {
    "openai_compatible": ProviderEntry(provider_id="openai", kind="openai_compatible", base_url="https://api.openai.com/v1"),
    "anthropic": ProviderEntry(provider_id="anthropic", kind="anthropic", base_url="https://api.anthropic.com/v1"),
}


def _model(kind: str) -> ModelEntry:
    return ModelEntry(
        model_id=f"{kind}-model",
        provider_id=kind,
        upstream_model="upstream",
        input_price_per_mtok=1.0,
        output_price_per_mtok=2.0,
        context_window=128000,
        capabilities=["streaming"],
    )


def make_ctx(kind: str) -> Ctx:
    return Ctx(request_id="req-1", model=_model(kind), provider=_PROVIDERS[kind], stream=True)


# ---------------------------------------------------------------------------- OpenAI


def _oa_encode(events: list[dict]) -> bytes:
    body = b"".join(b"data: " + json.dumps(e, ensure_ascii=False).encode() + b"\n\n" for e in events)
    return body + b"data: [DONE]\n\n"


def _oa_delta(delta: dict, finish: str | None = None) -> dict:
    return {"id": "cmpl-9", "model": "upstream", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


_OA_USAGE = {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}

_OPENAI = Case(
    kind="openai_compatible",
    ctx=make_ctx("openai_compatible"),
    encode=_oa_encode,
    text=Modality(
        events=[
            _oa_delta({"role": "assistant"}),
            _oa_delta({"content": "héllo "}),
            _oa_delta({"content": "\U0001f30d wor"}),
            _oa_delta({"content": "ld"}),
            _oa_delta({}, finish="stop"),
            {"id": "cmpl-9", "model": "upstream", "choices": [], "usage": _OA_USAGE},
        ],
        nonstream={
            "id": "cmpl-9",
            "model": "upstream",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "héllo \U0001f30d world"}, "finish_reason": "stop"}],
            "usage": _OA_USAGE,
        },
    ),
    tool=Modality(
        events=[
            _oa_delta({"role": "assistant"}),
            _oa_delta({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": ""}}]}),
            _oa_delta({"tool_calls": [{"index": 0, "function": {"arguments": '{"cit'}}]}),
            _oa_delta({"tool_calls": [{"index": 0, "function": {"arguments": 'y": "Paris"}'}}]}),
            _oa_delta({}, finish="tool_calls"),
            {"id": "cmpl-9", "model": "upstream", "choices": [], "usage": _OA_USAGE},
        ],
        nonstream={
            "id": "cmpl-9",
            "model": "upstream",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'}}],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": _OA_USAGE,
        },
    ),
    reasoning=Modality(
        events=[
            _oa_delta({"role": "assistant"}),
            _oa_delta({"reasoning_content": "The user wants "}),
            _oa_delta({"reasoning_content": "a sum: 2+2=4."}),
            _oa_delta({"content": "The answer "}),
            _oa_delta({"content": "is 4."}),
            _oa_delta({}, finish="stop"),
            {"id": "cmpl-9", "model": "upstream", "choices": [], "usage": _OA_USAGE},
        ],
        nonstream={
            "id": "cmpl-9",
            "model": "upstream",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "reasoning_content": "The user wants a sum: 2+2=4.", "content": "The answer is 4."},
                    "finish_reason": "stop",
                }
            ],
            "usage": _OA_USAGE,
        },
    ),
    error_log=_oa_encode([_oa_delta({"content": "hi"})])[: -len(b"data: [DONE]\n\n")]
    + b'data: {"error": {"code": "overloaded", "message": "slow down"}}\n\n',
)


# ---------------------------------------------------------------------------- Anthropic


def _an_encode(events: list[dict]) -> bytes:
    return b"".join(b"event: " + e["type"].encode() + b"\ndata: " + json.dumps(e, ensure_ascii=False).encode() + b"\n\n" for e in events)


def _an_message_start() -> dict:
    return {"type": "message_start", "message": {"id": "msg_1", "usage": {"input_tokens": 5, "output_tokens": 1}}}


def _an_stop(reason: str) -> list[dict]:
    return [
        {"type": "message_delta", "delta": {"stop_reason": reason}, "usage": {"output_tokens": 7}},
        {"type": "message_stop"},
    ]


_ANTHROPIC = Case(
    kind="anthropic",
    ctx=make_ctx("anthropic"),
    encode=_an_encode,
    text=Modality(
        events=[
            _an_message_start(),
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "héllo "}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "\U0001f30d world"}},
            {"type": "content_block_stop", "index": 0},
            *_an_stop("end_turn"),
        ],
        nonstream={
            "id": "msg_1",
            "model": "upstream",
            "content": [{"type": "text", "text": "héllo \U0001f30d world"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 7},
        },
    ),
    tool=Modality(
        events=[
            _an_message_start(),
            {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {}}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"cit'}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": 'y": "Paris"}'}},
            {"type": "content_block_stop", "index": 0},
            *_an_stop("tool_use"),
        ],
        nonstream={
            "id": "msg_1",
            "model": "upstream",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "Paris"}}],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 5, "output_tokens": 7},
        },
    ),
    reasoning=Modality(
        events=[
            _an_message_start(),
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "The user wants "}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "a sum: 2+2=4."}},
            {"type": "content_block_stop", "index": 0},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "The answer is 4."}},
            {"type": "content_block_stop", "index": 1},
            *_an_stop("end_turn"),
        ],
        nonstream={
            "id": "msg_1",
            "model": "upstream",
            "content": [{"type": "thinking", "thinking": "The user wants a sum: 2+2=4."}, {"type": "text", "text": "The answer is 4."}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 7},
        },
    ),
    error_log=_an_encode(
        [
            _an_message_start(),
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}},
            {"type": "error", "error": {"type": "overloaded_error", "message": "slow down"}},
        ]
    ),
)


CASES = [_OPENAI, _ANTHROPIC]
