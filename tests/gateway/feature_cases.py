from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from gateway_harness import Dialect
    from upstream import Family

Attachment = Literal["image", "document"]
CITY_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
}
WEATHER: dict[str, object] = {
    "name": "get_weather",
    "description": "Weather in a city",
    "parameters": CITY_SCHEMA,
}
TOOLS: dict[Dialect, list[dict[str, object]]] = {
    "canonical": [WEATHER],
    "openai_native": [{"type": "function", "function": WEATHER}],
    "openai_responses": [{"type": "function", **WEATHER}],
    "anthropic": [{"name": "get_weather", "description": "Weather in a city", "input_schema": CITY_SCHEMA}],
}
TOOL_EXPECTATIONS: dict[Family, list[dict[str, object]]] = {
    "openai_compatible": [{"type": "function", "function": {"name": "get_weather", "description": "Weather in a city", "parameters": CITY_SCHEMA}}],
    "openai_responses": [{"type": "function", "name": "get_weather", "description": "Weather in a city", "parameters": CITY_SCHEMA, "strict": None}],
    "anthropic": [{"name": "get_weather", "description": "Weather in a city", "input_schema": CITY_SCHEMA}],
}
INPUT_FIELDS: dict[Dialect, str] = {
    "canonical": "messages",
    "openai_native": "messages",
    "openai_responses": "input",
    "anthropic": "messages",
}
HISTORY_FIELDS: dict[Family, str] = {
    "openai_compatible": "messages",
    "openai_responses": "input",
    "anthropic": "messages",
}
_CONVERSATION: list[dict[str, object]] = [
    {"role": "user", "content": "Remember Paris"},
    {"role": "assistant", "content": "Paris remembered"},
    {"role": "user", "content": "What city?"},
]
CONVERSATION_REQUESTS: dict[Dialect, dict[str, object]] = {
    "canonical": {"messages": _CONVERSATION},
    "openai_native": {"messages": _CONVERSATION},
    "openai_responses": {"input": _CONVERSATION},
    "anthropic": {"messages": _CONVERSATION},
}
_EXPECTED_CONVERSATION: list[dict[str, object]] = [
    {"role": "user", "content": "Remember Paris"},
    {"role": "assistant", "content": "Paris remembered"},
    {"role": "user", "content": "What city?"},
]
CONVERSATION_EXPECTATIONS: dict[Family, dict[str, object]] = {
    "openai_compatible": {"messages": _EXPECTED_CONVERSATION},
    "openai_responses": {
        "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Remember Paris"}]},
            {"type": "message", "role": "assistant", "content": "Paris remembered"},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "What city?"}]},
        ]
    },
    "anthropic": {"messages": _EXPECTED_CONVERSATION},
}
_SYSTEM_MESSAGES: list[dict[str, object]] = [
    {"role": "system", "content": "Answer tersely"},
    {"role": "user", "content": "hi"},
]
SYSTEM_REQUESTS: dict[Dialect, dict[str, object]] = {
    "canonical": {"messages": _SYSTEM_MESSAGES},
    "openai_native": {"messages": _SYSTEM_MESSAGES},
    "openai_responses": {"instructions": "Answer tersely"},
    "anthropic": {"system": "Answer tersely"},
}
SYSTEM_EXPECTATIONS: dict[Family, dict[str, object]] = {
    "openai_compatible": {"messages": [{"role": "system", "content": "Answer tersely"}, {"role": "user", "content": "hi"}]},
    "openai_responses": {
        "input": [
            {"type": "message", "role": "system", "content": [{"type": "input_text", "text": "Answer tersely"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
        ]
    },
    "anthropic": {"system": "Answer tersely", "messages": [{"role": "user", "content": "hi"}]},
}
ATTACHMENT_CONTENT: dict[Dialect, dict[Attachment, list[dict[str, object]]]] = {
    "canonical": {
        "image": [
            {"type": "text", "text": "Before attachment"},
            {"type": "image", "media_type": "image/png", "data": "iVBORw0KGgo="},
            {"type": "text", "text": "After attachment"},
        ],
        "document": [
            {"type": "text", "text": "Before attachment"},
            {"type": "document", "media_type": "application/pdf", "data": "JVBERi0="},
            {"type": "text", "text": "After attachment"},
        ],
    },
    "openai_native": {
        "image": [
            {"type": "text", "text": "Before attachment"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
            {"type": "text", "text": "After attachment"},
        ],
        "document": [
            {"type": "text", "text": "Before attachment"},
            {"type": "file", "file": {"filename": "test.pdf", "file_data": "data:application/pdf;base64,JVBERi0="}},
            {"type": "text", "text": "After attachment"},
        ],
    },
    "openai_responses": {
        "image": [
            {"type": "input_text", "text": "Before attachment"},
            {"type": "input_image", "image_url": "data:image/png;base64,iVBORw0KGgo="},
            {"type": "input_text", "text": "After attachment"},
        ],
        "document": [
            {"type": "input_text", "text": "Before attachment"},
            {"type": "input_file", "filename": "test.pdf", "file_data": "data:application/pdf;base64,JVBERi0="},
            {"type": "input_text", "text": "After attachment"},
        ],
    },
    "anthropic": {
        "image": [
            {"type": "text", "text": "Before attachment"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}},
            {"type": "text", "text": "After attachment"},
        ],
        "document": [
            {"type": "text", "text": "Before attachment"},
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERi0="}},
            {"type": "text", "text": "After attachment"},
        ],
    },
}
AttachmentVariant = Literal["image", "document.pdf", "test.pdf"]
ATTACHMENT_VARIANTS: dict[Dialect, dict[Attachment, AttachmentVariant]] = {
    "canonical": {"image": "image", "document": "document.pdf"},
    "openai_native": {"image": "image", "document": "test.pdf"},
    "openai_responses": {"image": "image", "document": "test.pdf"},
    "anthropic": {"image": "image", "document": "document.pdf"},
}
ATTACHMENT_EXPECTATIONS: dict[Family, dict[AttachmentVariant, dict[str, object]]] = {
    "openai_compatible": {
        "image": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Before attachment"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
                        {"type": "text", "text": "After attachment"},
                    ],
                }
            ]
        },
        "document.pdf": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Before attachment"},
                        {"type": "file", "file": {"filename": "document.pdf", "file_data": "data:application/pdf;base64,JVBERi0="}},
                        {"type": "text", "text": "After attachment"},
                    ],
                }
            ]
        },
        "test.pdf": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Before attachment"},
                        {"type": "file", "file": {"filename": "test.pdf", "file_data": "data:application/pdf;base64,JVBERi0="}},
                        {"type": "text", "text": "After attachment"},
                    ],
                }
            ]
        },
    },
    "openai_responses": {
        "image": {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Before attachment"},
                        {"type": "input_image", "image_url": "data:image/png;base64,iVBORw0KGgo=", "detail": "auto"},
                        {"type": "input_text", "text": "After attachment"},
                    ],
                }
            ]
        },
        "document.pdf": {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Before attachment"},
                        {"type": "input_file", "filename": "document.pdf", "file_data": "data:application/pdf;base64,JVBERi0="},
                        {"type": "input_text", "text": "After attachment"},
                    ],
                }
            ]
        },
        "test.pdf": {
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Before attachment"},
                        {"type": "input_file", "filename": "test.pdf", "file_data": "data:application/pdf;base64,JVBERi0="},
                        {"type": "input_text", "text": "After attachment"},
                    ],
                }
            ]
        },
    },
    "anthropic": {
        "image": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Before attachment"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}},
                        {"type": "text", "text": "After attachment"},
                    ],
                }
            ]
        },
        "document.pdf": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Before attachment"},
                        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERi0="}},
                        {"type": "text", "text": "After attachment"},
                    ],
                }
            ]
        },
        "test.pdf": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Before attachment"},
                        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERi0="}},
                        {"type": "text", "text": "After attachment"},
                    ],
                }
            ]
        },
    },
}
STRUCTURED_REQUESTS: dict[Dialect, dict[str, object]] = {
    "canonical": {"response_format": {"type": "json_schema", "json_schema": {"name": "city", "schema": CITY_SCHEMA}}},
    "openai_native": {"response_format": {"type": "json_schema", "json_schema": {"name": "city", "schema": CITY_SCHEMA}}},
    "openai_responses": {"text": {"format": {"type": "json_schema", "name": "city", "schema": CITY_SCHEMA}}},
    "anthropic": {"output_config": {"format": {"type": "json_schema", "schema": CITY_SCHEMA}}},
}
StructuredVariant = Literal["named", "generated"]
STRUCTURED_VARIANTS: dict[Dialect, StructuredVariant] = {
    "canonical": "named",
    "openai_native": "named",
    "openai_responses": "named",
    "anthropic": "generated",
}
_EXPECTED_ANTHROPIC_SCHEMA: dict[str, object] = {"output_config": {"format": {"type": "json_schema", "schema": CITY_SCHEMA}}}
STRUCTURED_EXPECTATIONS: dict[Family, dict[StructuredVariant, dict[str, object]]] = {
    "openai_compatible": {
        "named": {"response_format": {"type": "json_schema", "json_schema": {"name": "city", "schema": CITY_SCHEMA}}},
        "generated": {"response_format": {"type": "json_schema", "json_schema": {"name": "response", "strict": True, "schema": CITY_SCHEMA}}},
    },
    "openai_responses": {
        "named": {"text": {"format": {"type": "json_schema", "name": "city", "schema": CITY_SCHEMA}}},
        "generated": {"text": {"format": {"type": "json_schema", "name": "response", "strict": True, "schema": CITY_SCHEMA}}},
    },
    "anthropic": {"named": _EXPECTED_ANTHROPIC_SCHEMA, "generated": _EXPECTED_ANTHROPIC_SCHEMA},
}
TOOL_HISTORY_REQUESTS: dict[Dialect, dict[str, object]] = {
    "canonical": {
        "messages": [
            {"role": "user", "content": "Weather in Paris?"},
            {"role": "assistant", "content": [{"type": "tool_call", "id": "call-weather", "name": "get_weather", "arguments": '{"city":"Paris"}'}]},
            {"role": "user", "content": [{"type": "tool_result", "call_id": "call-weather", "content": [{"type": "text", "text": "18C"}]}]},
        ]
    },
    "openai_native": {
        "messages": [
            {"role": "user", "content": "Weather in Paris?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-weather", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'}}],
            },
            {"role": "tool", "tool_call_id": "call-weather", "content": "18C"},
        ]
    },
    "openai_responses": {
        "input": [
            {"role": "user", "content": "Weather in Paris?"},
            {"type": "function_call", "call_id": "call-weather", "name": "get_weather", "arguments": '{"city":"Paris"}'},
            {"type": "function_call_output", "call_id": "call-weather", "output": "18C"},
        ]
    },
    "anthropic": {
        "messages": [
            {"role": "user", "content": "Weather in Paris?"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "call-weather", "name": "get_weather", "input": {"city": "Paris"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-weather", "content": "18C"}]},
        ]
    },
}
TOOL_HISTORY_EXPECTATIONS: dict[Family, list[dict[str, object]]] = {
    "openai_compatible": [
        {"role": "user", "content": "Weather in Paris?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call-weather", "type": "function", "function": {"name": "get_weather", "arguments": {"city": "Paris"}}}],
        },
        {"role": "tool", "tool_call_id": "call-weather", "content": "18C"},
    ],
    "openai_responses": [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Weather in Paris?"}]},
        {"type": "function_call", "call_id": "call-weather", "name": "get_weather", "arguments": {"city": "Paris"}},
        {"type": "function_call_output", "call_id": "call-weather", "output": "18C"},
    ],
    "anthropic": [
        {"role": "user", "content": "Weather in Paris?"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "call-weather", "name": "get_weather", "input": {"city": "Paris"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-weather", "content": [{"type": "text", "text": "18C"}]}]},
    ],
}
