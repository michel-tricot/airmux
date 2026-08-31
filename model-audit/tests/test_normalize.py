from __future__ import annotations

from model_audit.drivers.normalize import openai_chat, openai_chat_stream, openai_responses, openai_responses_stream


def test_chat_preserves_empty_reasoning_presence():
    observation = openai_chat(
        {"choices": [{"message": {"content": "42", "reasoning_content": ""}, "finish_reason": "stop"}], "usage": {"output_tokens": 8}},
        10,
        "HTTP JSON",
    )

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


def test_responses_prefers_the_gateway_canonical_finish_reason():
    observation = openai_responses(
        {
            "status": "completed",
            "output": [{"type": "function_call", "name": "lookup", "arguments": "{}"}],
            "gateway": {"finish_reason": "stop", "adjustments": []},
            "usage": {"output_tokens": 8},
        },
        10,
        "HTTP JSON",
    )

    assert observation.finish_reason == "stop"


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
