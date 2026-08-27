from __future__ import annotations

from model_audit.drivers.normalize import openai_responses_stream


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
