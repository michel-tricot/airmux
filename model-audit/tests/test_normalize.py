from __future__ import annotations

from model_audit.drivers.normalize import anthropic_message, openai_chat, openai_chat_stream, openai_responses, openai_responses_stream


def test_chat_preserves_empty_reasoning_presence():
    observation = openai_chat(
        {"choices": [{"message": {"content": "42", "reasoning_content": ""}, "finish_reason": "stop"}], "usage": {"output_tokens": 8}},
        10,
        "HTTP JSON",
    )

    assert observation.reasoning_present is True


def test_chat_preserves_typed_openai_compatible_content_blocks():
    observation = openai_chat(
        {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "thinking", "thinking": [{"type": "text", "text": "20 + 22"}]},
                            {"type": "text", "text": "42"},
                        ]
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"output_tokens": 8},
        },
        10,
        "HTTP JSON",
    )

    assert observation.text == "42"
    assert observation.reasoning_present is True


def test_chat_stream_preserves_empty_reasoning_presence():
    observation = openai_chat_stream(
        (
            {"choices": [{"delta": {"reasoning_content": ""}}]},
            {"choices": [{"delta": {"content": "42"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"output_tokens": 8}},
        ),
        10,
        "HTTP SSE",
    )

    assert observation.reasoning_present is True


def test_responses_function_call_has_a_tool_finish_reason():
    observation = openai_responses(
        {
            "status": "completed",
            "output": [{"type": "function_call", "name": "lookup", "arguments": "{}"}],
            "usage": {"output_tokens": 8},
        },
        10,
        "HTTP JSON",
    )

    assert observation.finish_reason == "tool_calls"


def test_responses_stream_preserves_failed_terminal_event():
    observation = openai_responses_stream(
        (
            {
                "type": "response.failed",
                "response": {
                    "status": "failed",
                    "error": {"code": "server_error", "message": "generation failed"},
                    "output": [],
                },
            },
        ),
        10,
        "HTTP SSE",
    )

    assert observation.outcome == "error"
    assert observation.error_code == "server_error"
    assert observation.error_message == "generation failed"


def test_responses_failed_rate_limit_is_transient():
    observation = openai_responses(
        {
            "status": "failed",
            "error": {"code": "rate_limit_exceeded", "message": "Please try again later"},
            "output": [],
        },
        10,
        "HTTP JSON",
    )

    assert observation.outcome == "transient"
    assert observation.error_code == "rate_limit_exceeded"


def test_responses_stream_preserves_top_level_error_event():
    observation = openai_responses_stream(
        (
            {
                "type": "error",
                "error": {"type": "upstream_error", "code": "slow_down", "message": "Please reduce request rate"},
            },
        ),
        10,
        "HTTP SSE",
    )

    assert observation.outcome == "transient"
    assert observation.error_code == "slow_down"
    assert observation.error_message == "Please reduce request rate"


def test_responses_stream_preserves_incomplete_terminal_event():
    observation = openai_responses_stream(
        (
            {
                "type": "response.incomplete",
                "response": {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "partial"}]}],
                    "usage": {"output_tokens": 8},
                },
            },
        ),
        10,
        "HTTP SSE",
    )

    assert observation.outcome == "success"
    assert observation.text == "partial"
    assert observation.finish_reason == "max_output_tokens"
    assert observation.usage_present is True


def test_chat_preserves_usage_counts_and_tool_identity():
    observation = openai_chat(
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [{"id": "call_123", "function": {"name": "lookup", "arguments": '{"city":"Paris"}'}}],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        },
        10,
        "HTTP JSON",
    )

    assert observation.usage is not None
    assert observation.usage.input_tokens == 12
    assert observation.usage.output_tokens == 4
    assert observation.usage.total_tokens == 16
    assert observation.tool_calls[0].id == "call_123"


def test_anthropic_preserves_usage_reasoning_signature_and_tool_identity():
    observation = anthropic_message(
        {
            "content": [
                {"type": "thinking", "thinking": "inspect", "signature": "signed"},
                {"type": "tool_use", "id": "toolu_123", "name": "lookup", "input": {"city": "Paris"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 14, "output_tokens": 6},
        },
        10,
        "HTTP JSON",
    )

    assert observation.usage is not None
    assert observation.usage.total_tokens == 20
    assert observation.reasoning is not None
    assert observation.reasoning.kind == "thinking"
    assert observation.reasoning.signature_present is True
    assert observation.tool_calls[0].id == "toolu_123"
