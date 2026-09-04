from __future__ import annotations

import pytest
from starlette.datastructures import Headers

from data_plane.ingress import resolve

TEXT_BODY = {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]}


TOOL_ROLE_BODY = {
    "model": "gpt-test",
    "messages": [
        {"role": "user", "content": "weather?"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "w", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "18C"},
    ],
}


NESTED_TOOLS_BODY = {**TEXT_BODY, "tools": [{"type": "function", "function": {"name": "w", "parameters": {}}}]}


IMAGE_URL_BODY = {
    "model": "gpt-test",
    "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://x/cat.png"}}]}],
}


@pytest.mark.parametrize(
    ("body", "headers", "expected"),
    [
        (TEXT_BODY, {}, False),
        (TOOL_ROLE_BODY, {}, True),
        (NESTED_TOOLS_BODY, {}, True),
        ({**TEXT_BODY, "tool_choice": {"type": "function", "function": {"name": "w"}}}, {}, True),
        (IMAGE_URL_BODY, {}, True),
        ({**TEXT_BODY, "max_completion_tokens": 5}, {}, True),
        (TEXT_BODY, {"x-stainless-lang": "python"}, False),  # every Stainless-built SDK sends these, not only OpenAI's
        (TEXT_BODY, {"user-agent": "OpenAI/Python 3.0.0"}, True),
        (TEXT_BODY, {"x-airllm-dialect": "openai_native"}, True),
        (TOOL_ROLE_BODY, {"x-airllm-dialect": "canonical"}, False),
        (TEXT_BODY, {"user-agent": "OpenAI/Python 3.0.0", "x-airllm-dialect": "canonical"}, False),
    ],
)
def test_openai_detection(body, headers, expected):
    assert (resolve(Headers(headers), body).dialect == "openai_native") is expected
