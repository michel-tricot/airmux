from __future__ import annotations

import json

from anthropic.types import Message

from data_plane.canonical import (
    CanonicalReasoningPart,
    CanonicalResponse,
    CanonicalTextPart,
    CanonicalUsage,
)
from data_plane.formats.openai_responses import ResponseMetadata, json_response
from data_plane.ingress.anthropic import AnthropicIngress
from data_plane.ingress.openai_native import OpenAINativeIngress


def test_openai_buffered_chat_preserves_an_empty_reasoning_part():
    final = CanonicalResponse(
        id="response-1",
        model="gpt-test",
        content=[CanonicalReasoningPart(id="rs_1", text="", signature="encrypted")],
        finish_reason="stop",
        usage=CanonicalUsage(input_tokens=3, output_tokens=2),
    )

    payload = json.loads(bytes(OpenAINativeIngress().render_response(final).body))

    assert payload["choices"][0]["message"]["reasoning_content"] == ""


def test_anthropic_the_sdk_reads_a_thinking_signature_back():
    """The signature must survive the render: a Messages caller replays it on the next turn."""
    final = CanonicalResponse(
        id="msg_1",
        model="m",
        content=[CanonicalReasoningPart(text="think", signature="sig_1"), CanonicalTextPart(text="ok")],
        finish_reason="stop",
        usage=CanonicalUsage(input_tokens=3, output_tokens=2),
    )
    message = Message.model_validate_json(bytes(AnthropicIngress().render_response(final).body))
    thinking = message.content[0]
    assert thinking.type == "thinking"
    assert (thinking.thinking, thinking.signature) == ("think", "sig_1")


def test_anthropic_the_sdk_replays_cross_provider_reasoning_identity():
    final = CanonicalResponse(
        id="msg_1",
        model="m",
        content=[CanonicalReasoningPart(id="rs_provider", text="think", signature="encrypted"), CanonicalTextPart(text="ok")],
        finish_reason="stop",
        usage=CanonicalUsage(input_tokens=3, output_tokens=2),
    )
    message = Message.model_validate_json(bytes(AnthropicIngress().render_response(final).body))

    request, _ = AnthropicIngress().parse(
        {
            "model": "m",
            "max_tokens": 64,
            "messages": [
                {"role": "assistant", "content": [block.model_dump() for block in message.content]},
                {"role": "user", "content": "continue"},
            ],
        }
    )

    assert request.messages[0].content[0] == CanonicalReasoningPart(id="rs_provider", text="think", signature="encrypted")


def test_responses_content_filter_is_visible_in_a_responses_reply():
    response = json_response(ResponseMetadata("response-1", "model-1", 1), [], "content_filter", CanonicalUsage())

    assert response["status"] == "incomplete"
    assert response["incomplete_details"] == {"reason": "content_filter"}


def test_responses_reasoning_response_preserves_the_provider_item_id():
    response = json_response(
        ResponseMetadata("response-1", "model-1", 1),
        [CanonicalReasoningPart(id="rs_provider", text="thinking", signature="encrypted")],
        "stop",
        CanonicalUsage(),
    )

    assert response["output"][0]["id"] == "rs_provider"
