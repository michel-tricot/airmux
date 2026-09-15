from __future__ import annotations

import json
from copy import deepcopy
from typing import TYPE_CHECKING, Literal

import pytest
from gateway_harness import DIALECTS, FAMILIES, request_body, stream_payloads, streamed_text, text_of
from pydantic import TypeAdapter
from upstream import ARGUMENTS, TEXT, Reply

if TYPE_CHECKING:
    from gateway_harness import Dialect, Gateway
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
CALLER_MESSAGE_FIELDS: dict[Dialect, str] = {
    "canonical": "messages",
    "openai_native": "messages",
    "openai_responses": "input",
    "anthropic": "messages",
}
PROVIDER_MESSAGE_FIELDS: dict[Family, str] = {
    "openai_compatible": "messages",
    "openai_responses": "input",
    "anthropic": "messages",
}


def buffered_tool_call(dialect: Dialect, response) -> tuple[str, str, str]:
    body = response.json()
    if dialect == "openai_native":
        tool = body["choices"][0]["message"]["tool_calls"][0]
        return tool["id"], tool["function"]["name"], tool["function"]["arguments"]
    if dialect == "openai_responses":
        tool = next(item for item in body["output"] if item["type"] == "function_call")
        return tool["call_id"], tool["name"], tool["arguments"]
    tool = next(part for part in body["content"] if part["type"] in ("tool_call", "tool_use"))
    return tool["id"], tool["name"], json.dumps(tool["input"]) if dialect == "anthropic" else tool["arguments"]


def streamed_tool_call(dialect: Dialect, response) -> tuple[str, str, str]:
    payloads = stream_payloads(response)
    if dialect == "canonical":
        deltas = [event["delta"] for event in payloads if event.get("delta", {}).get("type") == "tool_call"]
        return deltas[0]["id"], deltas[0]["name"], "".join(delta.get("arguments", "") for delta in deltas)
    if dialect == "openai_native":
        tools = [tool for event in payloads for choice in event.get("choices", []) for tool in choice["delta"].get("tool_calls", [])]
        return tools[0]["id"], tools[0]["function"]["name"], "".join(tool.get("function", {}).get("arguments", "") for tool in tools)
    if dialect == "openai_responses":
        tool = next(event["item"] for event in payloads if event.get("type") == "response.output_item.added")
        arguments = "".join(event["delta"] for event in payloads if event.get("type") == "response.function_call_arguments.delta")
        return tool["call_id"], tool["name"], arguments
    tool = next(event["content_block"] for event in payloads if event.get("type") == "content_block_start")
    arguments = "".join(event["delta"]["partial_json"] for event in payloads if event.get("type") == "content_block_delta")
    return tool["id"], tool["name"], arguments


def streamed_reasoning(dialect: Dialect, response) -> str:
    payloads = stream_payloads(response)
    if dialect == "canonical":
        return "".join(event["delta"]["text"] for event in payloads if event.get("delta", {}).get("type") == "reasoning")
    if dialect == "openai_native":
        return "".join(choice["delta"].get("reasoning_content", "") for event in payloads for choice in event.get("choices", []))
    if dialect == "openai_responses":
        return "".join(event["delta"] for event in payloads if event.get("type") == "response.reasoning_summary_text.delta")
    return "".join(
        event["delta"]["thinking"] for event in payloads if event.get("type") == "content_block_delta" and event["delta"]["type"] == "thinking_delta"
    )


def buffered_reasoning(dialect: Dialect, response) -> str:
    body = response.json()
    if dialect == "openai_native":
        return body["choices"][0]["message"]["reasoning_content"]
    if dialect == "openai_responses":
        return "".join(part["text"] for item in body["output"] if item["type"] == "reasoning" for part in item["summary"])
    if dialect == "anthropic":
        return "".join(part["thinking"] for part in body["content"] if part["type"] == "thinking")
    return "".join(part["text"] for part in body["content"] if part["type"] == "reasoning")


def tool_history_of(family: Family, body: dict[str, object]) -> list[dict[str, object]]:
    messages = deepcopy(TypeAdapter(list[dict[str, object]]).validate_python(body[PROVIDER_MESSAGE_FIELDS[family]]))
    if family == "openai_compatible":
        calls = TypeAdapter(list[dict[str, object]]).validate_python(messages[1]["tool_calls"])
        function = TypeAdapter(dict[str, object]).validate_python(calls[0]["function"])
        arguments = TypeAdapter(str).validate_python(function["arguments"], strict=True)
        function["arguments"] = json.loads(arguments)
        calls[0]["function"] = function
        messages[1]["tool_calls"] = calls
    elif family == "openai_responses":
        arguments = TypeAdapter(str).validate_python(messages[1]["arguments"], strict=True)
        messages[1]["arguments"] = json.loads(arguments)
    return messages


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_tool_names_ids_and_fragmented_arguments_survive_every_protocol_pair(gateway: Gateway, dialect: Dialect, family: Family, stream: bool):
    expected_tools: dict[Family, list[dict[str, object]]] = {
        "openai_compatible": [
            {"type": "function", "function": {"name": "get_weather", "description": "Weather in a city", "parameters": CITY_SCHEMA}}
        ],
        "openai_responses": [
            {"type": "function", "name": "get_weather", "description": "Weather in a city", "parameters": CITY_SCHEMA, "strict": None}
        ],
        "anthropic": [{"name": "get_weather", "description": "Weather in a city", "input_schema": CITY_SCHEMA}],
    }
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(content="tool")
    gateway.start()
    response = gateway.request(dialect, tools=TOOLS[dialect], stream=stream)
    assert response.status_code == 200, response.text
    tool_id, name, arguments = streamed_tool_call(dialect, response) if stream else buffered_tool_call(dialect, response)
    assert (tool_id, name, json.loads(arguments)) == ("call-weather", "get_weather", json.loads(ARGUMENTS))
    assert provider.requests[0].body["tools"] == expected_tools[family]
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_reasoning_and_answer_survive_every_protocol_pair(gateway: Gateway, dialect: Dialect, family: Family, stream: bool):
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(content="reasoning")
    gateway.start()
    response = gateway.request(dialect, stream=stream)
    assert response.status_code == 200, response.text
    assert (streamed_reasoning(dialect, response) if stream else buffered_reasoning(dialect, response)) == "Think carefully"
    assert (streamed_text(dialect, response) if stream else text_of(dialect, response)) == TEXT
    assert gateway.events(1)[0].output_tokens == 3


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_conversation_preserves_every_role_and_turn(gateway: Gateway, dialect: Dialect, family: Family):
    messages: list[dict[str, object]] = [
        {"role": "user", "content": "Remember Paris"},
        {"role": "assistant", "content": "Paris remembered"},
        {"role": "user", "content": "What city?"},
    ]
    expected_turns: list[dict[str, object]] = [
        {"role": "user", "content": "Remember Paris"},
        {"role": "assistant", "content": "Paris remembered"},
        {"role": "user", "content": "What city?"},
    ]
    expected_messages: dict[Family, list[dict[str, object]]] = {
        "openai_compatible": expected_turns,
        "openai_responses": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Remember Paris"}]},
            {"type": "message", "role": "assistant", "content": "Paris remembered"},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "What city?"}]},
        ],
        "anthropic": expected_turns,
    }
    provider = gateway.add_provider(family)
    gateway.start()
    response = gateway.request(dialect, body={**request_body(dialect), CALLER_MESSAGE_FIELDS[dialect]: messages})
    assert response.status_code == 200, response.text
    assert provider.requests[0].body[PROVIDER_MESSAGE_FIELDS[family]] == expected_messages[family]
    assert text_of(dialect, response) == TEXT
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_system_prompt_reaches_the_provider_in_its_designated_field(gateway: Gateway, dialect: Dialect, family: Family):
    system_messages: list[dict[str, object]] = [
        {"role": "system", "content": "Answer tersely"},
        {"role": "user", "content": "hi"},
    ]
    caller_prompts: dict[Dialect, dict[str, object]] = {
        "canonical": {"messages": system_messages},
        "openai_native": {"messages": system_messages},
        "openai_responses": {"instructions": "Answer tersely"},
        "anthropic": {"system": "Answer tersely"},
    }
    expected_prompts: dict[Family, dict[str, object]] = {
        "openai_compatible": {"messages": [{"role": "system", "content": "Answer tersely"}, {"role": "user", "content": "hi"}]},
        "openai_responses": {
            "input": [
                {"type": "message", "role": "system", "content": [{"type": "input_text", "text": "Answer tersely"}]},
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
            ]
        },
        "anthropic": {"system": "Answer tersely", "messages": [{"role": "user", "content": "hi"}]},
    }
    provider = gateway.add_provider(family)
    gateway.start()
    response = gateway.request(dialect, body={**request_body(dialect), **caller_prompts[dialect]})
    assert response.status_code == 200, response.text
    for field, expected in expected_prompts[family].items():
        assert provider.requests[0].body[field] == expected
    assert text_of(dialect, response) == TEXT
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("attachment", ["image", "document"])
def test_inline_content_preserves_type_media_data_and_order(gateway: Gateway, dialect: Dialect, family: Family, attachment: Attachment):
    caller_attachments: dict[Dialect, dict[Attachment, dict[str, object]]] = {
        "canonical": {
            "image": {"type": "image", "media_type": "image/png", "data": "iVBORw0KGgo="},
            "document": {"type": "document", "media_type": "application/pdf", "data": "JVBERi0="},
        },
        "openai_native": {
            "image": {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
            "document": {"type": "file", "file": {"filename": "test.pdf", "file_data": "data:application/pdf;base64,JVBERi0="}},
        },
        "openai_responses": {
            "image": {"type": "input_image", "image_url": "data:image/png;base64,iVBORw0KGgo="},
            "document": {"type": "input_file", "filename": "test.pdf", "file_data": "data:application/pdf;base64,JVBERi0="},
        },
        "anthropic": {
            "image": {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}},
            "document": {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERi0="}},
        },
    }
    expected_filename = {"canonical": "document.pdf", "openai_native": "test.pdf", "openai_responses": "test.pdf", "anthropic": "document.pdf"}[
        dialect
    ]
    provider_attachments: dict[Family, dict[Attachment, dict[str, object]]] = {
        "openai_compatible": {
            "image": {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
            "document": {"type": "file", "file": {"filename": expected_filename, "file_data": "data:application/pdf;base64,JVBERi0="}},
        },
        "openai_responses": {
            "image": {"type": "input_image", "image_url": "data:image/png;base64,iVBORw0KGgo=", "detail": "auto"},
            "document": {"type": "input_file", "filename": expected_filename, "file_data": "data:application/pdf;base64,JVBERi0="},
        },
        "anthropic": {
            "image": {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}},
            "document": {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERi0="}},
        },
    }
    caller_text_type = {"canonical": "text", "openai_native": "text", "openai_responses": "input_text", "anthropic": "text"}[dialect]
    provider_text_type = {"openai_compatible": "text", "openai_responses": "input_text", "anthropic": "text"}[family]
    provider = gateway.add_provider(family)
    gateway.start()
    body = {
        **request_body(dialect),
        CALLER_MESSAGE_FIELDS[dialect]: [
            {
                "role": "user",
                "content": [
                    {"type": caller_text_type, "text": "Before attachment"},
                    caller_attachments[dialect][attachment],
                    {"type": caller_text_type, "text": "After attachment"},
                ],
            }
        ],
    }
    response = gateway.request(dialect, body=body)
    assert response.status_code == 200, response.text
    assert provider.requests[0].body[PROVIDER_MESSAGE_FIELDS[family]] == [
        {
            **{"openai_compatible": {}, "openai_responses": {"type": "message"}, "anthropic": {}}[family],
            "role": "user",
            "content": [
                {"type": provider_text_type, "text": "Before attachment"},
                provider_attachments[family][attachment],
                {"type": provider_text_type, "text": "After attachment"},
            ],
        }
    ]
    assert text_of(dialect, response) == TEXT
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_structured_output_schema_reaches_the_provider(gateway: Gateway, dialect: Dialect, family: Family):
    caller_formats: dict[Dialect, dict[str, object]] = {
        "canonical": {"response_format": {"type": "json_schema", "json_schema": {"name": "city", "schema": CITY_SCHEMA}}},
        "openai_native": {"response_format": {"type": "json_schema", "json_schema": {"name": "city", "schema": CITY_SCHEMA}}},
        "openai_responses": {"text": {"format": {"type": "json_schema", "name": "city", "schema": CITY_SCHEMA}}},
        "anthropic": {"output_config": {"format": {"type": "json_schema", "schema": CITY_SCHEMA}}},
    }
    expected_metadata = {
        "canonical": {"name": "city"},
        "openai_native": {"name": "city"},
        "openai_responses": {"name": "city"},
        "anthropic": {"name": "response", "strict": True},
    }[dialect]
    expected_formats: dict[Family, dict[str, object]] = {
        "openai_compatible": {"response_format": {"type": "json_schema", "json_schema": {**expected_metadata, "schema": CITY_SCHEMA}}},
        "openai_responses": {"text": {"format": {"type": "json_schema", **expected_metadata, "schema": CITY_SCHEMA}}},
        "anthropic": {"output_config": {"format": {"type": "json_schema", "schema": CITY_SCHEMA}}},
    }
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(text='{"city":"Paris"}')
    gateway.start()
    response = gateway.request(dialect, body={**request_body(dialect), **caller_formats[dialect]})
    assert response.status_code == 200, response.text
    for field, expected in expected_formats[family].items():
        assert provider.requests[0].body[field] == expected
    assert json.loads(text_of(dialect, response)) == {"city": "Paris"}
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_tool_result_keeps_its_relationship_to_the_assistant_call(gateway: Gateway, dialect: Dialect, family: Family):
    caller_histories: dict[Dialect, list[dict[str, object]]] = {
        "canonical": [
            {"role": "assistant", "content": [{"type": "tool_call", "id": "call-weather", "name": "get_weather", "arguments": '{"city":"Paris"}'}]},
            {"role": "user", "content": [{"type": "tool_result", "call_id": "call-weather", "content": [{"type": "text", "text": "18C"}]}]},
        ],
        "openai_native": [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-weather", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'}}],
            },
            {"role": "tool", "tool_call_id": "call-weather", "content": "18C"},
        ],
        "openai_responses": [
            {"type": "function_call", "call_id": "call-weather", "name": "get_weather", "arguments": '{"city":"Paris"}'},
            {"type": "function_call_output", "call_id": "call-weather", "output": "18C"},
        ],
        "anthropic": [
            {"role": "assistant", "content": [{"type": "tool_use", "id": "call-weather", "name": "get_weather", "input": {"city": "Paris"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-weather", "content": "18C"}]},
        ],
    }
    expected_histories: dict[Family, list[dict[str, object]]] = {
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
    provider = gateway.add_provider(family)
    gateway.start()
    body = {
        **request_body(dialect, tools=TOOLS[dialect]),
        CALLER_MESSAGE_FIELDS[dialect]: [{"role": "user", "content": "Weather in Paris?"}, *caller_histories[dialect]],
    }
    response = gateway.request(dialect, body=body)
    assert response.status_code == 200, response.text
    assert tool_history_of(family, provider.requests[0].body) == expected_histories[family]
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("alias_input", [False, True], ids=["canonical_parameter", "provider_alias"])
def test_provider_aliases_cannot_bypass_the_canonical_parameter_boundary(gateway: Gateway, family: Family, alias_input: bool):
    provider = gateway.add_provider(family)
    gateway.taxonomy["providers"][0]["param_aliases"] = {"temperature": "provider_temperature"}
    gateway.start()
    response = gateway.request(body={**request_body("canonical"), "provider_temperature" if alias_input else "temperature": 0.5})
    assert response.status_code == (400 if alias_input else 200)
    if alias_input:
        assert provider.requests == []
        assert gateway.events(0) == []
    else:
        assert provider.requests[0].body["provider_temperature"] == 0.5
        assert "temperature" not in provider.requests[0].body
        assert gateway.events(1)[0].status == "ok"
