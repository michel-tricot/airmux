from __future__ import annotations

import json
from copy import deepcopy
from typing import TYPE_CHECKING

import pytest
from feature_cases import (
    ATTACHMENT_CONTENT,
    ATTACHMENT_EXPECTATIONS,
    ATTACHMENT_VARIANTS,
    CONVERSATION_EXPECTATIONS,
    CONVERSATION_REQUESTS,
    HISTORY_FIELDS,
    INPUT_FIELDS,
    STRUCTURED_EXPECTATIONS,
    STRUCTURED_REQUESTS,
    STRUCTURED_VARIANTS,
    SYSTEM_EXPECTATIONS,
    SYSTEM_REQUESTS,
    TOOL_EXPECTATIONS,
    TOOL_HISTORY_EXPECTATIONS,
    TOOL_HISTORY_REQUESTS,
    TOOLS,
)
from gateway_harness import DIALECTS, FAMILIES, request_body, stream_payloads, streamed_text, text_of
from pydantic import TypeAdapter
from upstream import ARGUMENTS, TEXT, Reply

if TYPE_CHECKING:
    from feature_cases import Attachment
    from gateway_harness import Dialect, Gateway
    from upstream import Family


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
    messages = deepcopy(TypeAdapter(list[dict[str, object]]).validate_python(body[HISTORY_FIELDS[family]]))
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
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(content="tool")
    gateway.start()
    response = gateway.request(dialect, tools=TOOLS[dialect], stream=stream)
    assert response.status_code == 200, response.text
    tool_id, name, arguments = streamed_tool_call(dialect, response) if stream else buffered_tool_call(dialect, response)
    assert (tool_id, name, json.loads(arguments)) == ("call-weather", "get_weather", json.loads(ARGUMENTS))
    assert provider.requests[0].body["tools"] == TOOL_EXPECTATIONS[family]
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
    response = gateway.request(dialect, body={**request_body(dialect), **CONVERSATION_REQUESTS[dialect]})
    assert response.status_code == 200, response.text
    for field, expected in CONVERSATION_EXPECTATIONS[family].items():
        assert provider.requests[0].body[field] == expected
    assert text_of(dialect, response) == TEXT
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_system_prompt_reaches_the_provider_in_its_designated_field(gateway: Gateway, dialect: Dialect, family: Family):
    provider = gateway.add_provider(family)
    gateway.start()
    response = gateway.request(dialect, body={**request_body(dialect), **SYSTEM_REQUESTS[dialect]})
    assert response.status_code == 200, response.text
    for field, expected in SYSTEM_EXPECTATIONS[family].items():
        assert provider.requests[0].body[field] == expected
    assert text_of(dialect, response) == TEXT
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("attachment", ["image", "document"])
def test_inline_content_preserves_type_media_data_and_order(gateway: Gateway, dialect: Dialect, family: Family, attachment: Attachment):
    provider = gateway.add_provider(family)
    gateway.start()
    body = {
        **request_body(dialect),
        INPUT_FIELDS[dialect]: [{"role": "user", "content": ATTACHMENT_CONTENT[dialect][attachment]}],
    }
    response = gateway.request(dialect, body=body)
    assert response.status_code == 200, response.text
    variant = ATTACHMENT_VARIANTS[dialect][attachment]
    for field, expected in ATTACHMENT_EXPECTATIONS[family][variant].items():
        assert provider.requests[0].body[field] == expected
    assert text_of(dialect, response) == TEXT
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_structured_output_schema_reaches_the_provider(gateway: Gateway, dialect: Dialect, family: Family):
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(text='{"city":"Paris"}')
    gateway.start()
    response = gateway.request(dialect, body={**request_body(dialect), **STRUCTURED_REQUESTS[dialect]})
    assert response.status_code == 200, response.text
    for field, expected in STRUCTURED_EXPECTATIONS[family][STRUCTURED_VARIANTS[dialect]].items():
        assert provider.requests[0].body[field] == expected
    assert json.loads(text_of(dialect, response)) == {"city": "Paris"}
    assert gateway.events(1)[0].status == "ok"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
def test_tool_result_keeps_its_relationship_to_the_assistant_call(gateway: Gateway, dialect: Dialect, family: Family):
    provider = gateway.add_provider(family)
    gateway.start()
    body = {**request_body(dialect, tools=TOOLS[dialect]), **TOOL_HISTORY_REQUESTS[dialect]}
    response = gateway.request(dialect, body=body)
    assert response.status_code == 200, response.text
    assert tool_history_of(family, provider.requests[0].body) == TOOL_HISTORY_EXPECTATIONS[family]
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
