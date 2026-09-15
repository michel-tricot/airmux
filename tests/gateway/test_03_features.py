from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

import pytest
from gateway_harness import DIALECTS, FAMILIES, request_body, stream_payloads, streamed_text, text_of
from pydantic import TypeAdapter
from upstream import ARGUMENTS, TEXT, Reply

if TYPE_CHECKING:
    from gateway_harness import Dialect, Gateway
    from upstream import Family

Attachment = Literal["image", "document"]
WEATHER: dict[str, object] = {
    "name": "get_weather",
    "description": "Weather in a city",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}


def tools_of(dialect: Dialect) -> list[dict[str, object]]:
    if dialect == "openai_native":
        return [{"type": "function", "function": WEATHER}]
    if dialect == "openai_responses":
        return [{"type": "function", **WEATHER}]
    if dialect == "anthropic":
        return [{"name": WEATHER["name"], "description": WEATHER["description"], "input_schema": WEATHER["parameters"]}]
    return [WEATHER]


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


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_tool_names_ids_and_fragmented_arguments_survive_every_protocol_pair(gateway: Gateway, dialect: Dialect, family: Family, stream: bool):
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(content="tool")
    gateway.start()
    response = gateway.request(dialect, tools=tools_of(dialect), stream=stream)
    assert response.status_code == 200, response.text
    tool_id, name, arguments = streamed_tool_call(dialect, response) if stream else buffered_tool_call(dialect, response)
    assert (tool_id, name, json.loads(arguments)) == ("call-weather", "get_weather", json.loads(ARGUMENTS))
    sent = provider.requests[0].body["tools"]
    if family == "anthropic":
        assert sent == [{"name": "get_weather", "description": "Weather in a city", "input_schema": WEATHER["parameters"]}]
    elif family == "openai_responses":
        assert sent == [{"type": "function", **WEATHER, "strict": None}]
    else:
        assert sent == [{"type": "function", "function": WEATHER}]
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
    provider = gateway.add_provider(family)
    gateway.start()
    messages = [
        {"role": "user", "content": "Remember Paris"},
        {"role": "assistant", "content": "Paris remembered"},
        {"role": "user", "content": "What city?"},
    ]
    response = gateway.request(dialect, body={**request_body(dialect), "input" if dialect == "openai_responses" else "messages": messages})
    assert response.status_code == 200, response.text
    sent = provider.requests[0].body
    if family == "openai_responses":
        assert sent["input"] == [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Remember Paris"}]},
            {"type": "message", "role": "assistant", "content": "Paris remembered"},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "What city?"}]},
        ]
    else:
        assert sent["messages"] == messages
    assert text_of(dialect, response) == TEXT
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_system_prompt_reaches_the_provider_in_its_designated_field(gateway: Gateway, dialect: Dialect, family: Family):
    provider = gateway.add_provider(family)
    gateway.start()
    body = request_body(dialect)
    if dialect == "openai_responses":
        body["instructions"] = "Answer tersely"
    elif dialect == "anthropic":
        body["system"] = "Answer tersely"
    else:
        body["messages"] = [{"role": "system", "content": "Answer tersely"}, {"role": "user", "content": "hi"}]
    response = gateway.request(dialect, body=body)
    assert response.status_code == 200, response.text
    sent = provider.requests[0].body
    if family == "anthropic":
        assert sent["system"] == "Answer tersely"
        assert sent["messages"] == [{"role": "user", "content": "hi"}]
    elif family == "openai_responses":
        assert sent["input"] == [
            {"type": "message", "role": "system", "content": [{"type": "input_text", "text": "Answer tersely"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
        ]
    else:
        assert sent["messages"] == [{"role": "system", "content": "Answer tersely"}, {"role": "user", "content": "hi"}]
    assert text_of(dialect, response) == TEXT
    assert gateway.events(1)[0].status == "ok"


def attachment_request(dialect: Dialect, attachment: Attachment) -> dict[str, object]:
    image = attachment == "image"
    data = "iVBORw0KGgo=" if image else "JVBERi0="
    media_type = "image/png" if image else "application/pdf"
    if dialect == "canonical":
        part = {"type": "image" if image else "document", "media_type": media_type, "data": data}
    elif dialect == "anthropic":
        part = {"type": "image" if image else "document", "source": {"type": "base64", "media_type": media_type, "data": data}}
    elif dialect == "openai_responses":
        part = (
            {"type": "input_image", "image_url": f"data:{media_type};base64,{data}"}
            if image
            else {"type": "input_file", "filename": "test.pdf", "file_data": f"data:{media_type};base64,{data}"}
        )
    else:
        part = (
            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}}
            if image
            else {"type": "file", "file": {"filename": "test.pdf", "file_data": f"data:{media_type};base64,{data}"}}
        )
    text_type = "input_text" if dialect == "openai_responses" else "text"
    return {
        **request_body(dialect),
        "input" if dialect == "openai_responses" else "messages": [
            {
                "role": "user",
                "content": [{"type": text_type, "text": "Before attachment"}, part, {"type": text_type, "text": "After attachment"}],
            }
        ],
    }


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("attachment", ["image", "document"])
def test_inline_content_preserves_type_media_data_and_order(gateway: Gateway, dialect: Dialect, family: Family, attachment: Attachment):
    provider = gateway.add_provider(family)
    gateway.start()
    response = gateway.request(dialect, body=attachment_request(dialect, attachment))
    assert response.status_code == 200, response.text
    sent = provider.requests[0].body
    filename = "test.pdf" if dialect in ("openai_native", "openai_responses") else "document.pdf"
    if family == "anthropic":
        part = (
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}
            if attachment == "image"
            else {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "JVBERi0="}}
        )
    elif family == "openai_responses":
        part = (
            {"type": "input_image", "image_url": "data:image/png;base64,iVBORw0KGgo=", "detail": "auto"}
            if attachment == "image"
            else {"type": "input_file", "filename": filename, "file_data": "data:application/pdf;base64,JVBERi0="}
        )
    else:
        part = (
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}
            if attachment == "image"
            else {"type": "file", "file": {"filename": filename, "file_data": "data:application/pdf;base64,JVBERi0="}}
        )
    text_type = "input_text" if family == "openai_responses" else "text"
    message = {"role": "user", "content": [{"type": text_type, "text": "Before attachment"}, part, {"type": text_type, "text": "After attachment"}]}
    if family == "openai_responses":
        assert sent["input"] == [{"type": "message", **message}]
    else:
        assert sent["messages"] == [message]
    assert text_of(dialect, response) == TEXT
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_structured_output_schema_reaches_the_provider(gateway: Gateway, dialect: Dialect, family: Family):
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(text='{"city":"Paris"}')
    gateway.start()
    schema = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
    if dialect == "anthropic":
        parameters = {"output_config": {"format": {"type": "json_schema", "schema": schema}}}
    elif dialect == "openai_responses":
        parameters = {"text": {"format": {"type": "json_schema", "name": "city", "schema": schema}}}
    else:
        parameters = {"response_format": {"type": "json_schema", "json_schema": {"name": "city", "schema": schema}}}
    response = gateway.request(dialect, body={**request_body(dialect), **parameters})
    assert response.status_code == 200, response.text
    sent = provider.requests[0].body
    json_schema = {"name": "response", "strict": True, "schema": schema} if dialect == "anthropic" else {"name": "city", "schema": schema}
    if family == "anthropic":
        assert sent["output_config"] == {"format": {"type": "json_schema", "schema": schema}}
    elif family == "openai_responses":
        assert sent["text"] == {"format": {"type": "json_schema", **json_schema}}
    else:
        assert sent["response_format"] == {"type": "json_schema", "json_schema": json_schema}
    assert json.loads(text_of(dialect, response)) == {"city": "Paris"}
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_tool_result_keeps_its_relationship_to_the_assistant_call(gateway: Gateway, dialect: Dialect, family: Family):
    provider = gateway.add_provider(family)
    gateway.start()
    body = request_body(dialect, tools=tools_of(dialect))
    user = {"role": "user", "content": "Weather in Paris?"}
    if dialect == "canonical":
        messages = [
            user,
            {"role": "assistant", "content": [{"type": "tool_call", "id": "call-weather", "name": "get_weather", "arguments": ARGUMENTS}]},
            {"role": "user", "content": [{"type": "tool_result", "call_id": "call-weather", "content": [{"type": "text", "text": "18C"}]}]},
        ]
    elif dialect == "openai_native":
        messages = [
            user,
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-weather", "type": "function", "function": {"name": "get_weather", "arguments": ARGUMENTS}}],
            },
            {"role": "tool", "tool_call_id": "call-weather", "content": "18C"},
        ]
    elif dialect == "anthropic":
        messages = [
            user,
            {"role": "assistant", "content": [{"type": "tool_use", "id": "call-weather", "name": "get_weather", "input": {"city": "Paris"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-weather", "content": "18C"}]},
        ]
    else:
        messages = [
            user,
            {"type": "function_call", "call_id": "call-weather", "name": "get_weather", "arguments": ARGUMENTS},
            {"type": "function_call_output", "call_id": "call-weather", "output": "18C"},
        ]
    body["input" if dialect == "openai_responses" else "messages"] = messages
    response = gateway.request(dialect, body=body)
    assert response.status_code == 200, response.text
    sent = provider.requests[0].body
    messages = TypeAdapter(list[dict[str, object]]).validate_python(sent["input" if family == "openai_responses" else "messages"])
    if family == "openai_compatible":
        calls = TypeAdapter(list[dict[str, object]]).validate_python(messages[1]["tool_calls"])
        function = TypeAdapter(dict[str, object]).validate_python(calls[0]["function"])
        arguments = TypeAdapter(str).validate_python(function["arguments"])
        assert messages == [
            {"role": "user", "content": "Weather in Paris?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-weather", "type": "function", "function": {"name": "get_weather", "arguments": arguments}}],
            },
            {"role": "tool", "tool_call_id": "call-weather", "content": "18C"},
        ]
        assert json.loads(arguments) == {"city": "Paris"}
    elif family == "openai_responses":
        arguments = TypeAdapter(str).validate_python(messages[1]["arguments"])
        assert messages == [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Weather in Paris?"}]},
            {"type": "function_call", "call_id": "call-weather", "name": "get_weather", "arguments": arguments},
            {"type": "function_call_output", "call_id": "call-weather", "output": "18C"},
        ]
        assert json.loads(arguments) == {"city": "Paris"}
    else:
        assert messages == [
            {"role": "user", "content": "Weather in Paris?"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "call-weather", "name": "get_weather", "input": {"city": "Paris"}}]},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "call-weather", "content": [{"type": "text", "text": "18C"}]}],
            },
        ]
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
