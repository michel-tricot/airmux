from __future__ import annotations

import pytest

from data_plane.canonical import CanonicalRequest
from data_plane.requirements import RequestRequirements


@pytest.mark.parametrize(
    ("body", "capabilities", "modalities"),
    [
        ({}, set(), set()),
        ({"stream": True}, {"streaming"}, set()),
        ({"tool_choice": "auto"}, {"tools"}, set()),
        ({"reasoning": {"effort": "high"}}, {"reasoning"}, set()),
        ({"response_format": {"type": "json_object"}}, {"structured_output"}, set()),
        (
            {
                "messages": [
                    {"role": "user", "content": [{"type": "image", "url": "https://example.com/image"}, {"type": "document", "file_id": "doc"}]}
                ]
            },
            set(),
            {"image", "pdf"},
        ),
        (
            {
                "stream": True,
                "messages": [
                    {
                        "role": "assistant",
                        "content": [{"type": "reasoning", "text": "thought"}, {"type": "tool_call", "id": "call", "name": "tool", "arguments": "{}"}],
                    }
                ],
            },
            {"streaming", "reasoning", "tools"},
            set(),
        ),
    ],
)
def test_requirements_describe_the_requested_features(body, capabilities, modalities):
    request = CanonicalRequest.model_validate({"model": "model", "messages": [{"role": "user", "content": "hello"}], **body})
    requirements = RequestRequirements.of(request)

    assert requirements.capabilities == capabilities
    assert requirements.input_modalities == modalities
    assert requirements.requested_capabilities == capabilities - {"streaming"}
    assert RequestRequirements.of(request.model_copy(update={"model": "fallback"})) == requirements
