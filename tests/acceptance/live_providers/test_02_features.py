from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from tests.acceptance.gateway.gateway_harness import FAMILIES, request_body, stream_payloads, streamed_text, text_of

if TYPE_CHECKING:
    from live_harness import LiveGateway

CITY_SCHEMA = {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"], "additionalProperties": False}


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_live_tool_call(live_gateway: LiveGateway, stream: bool) -> None:
    live_gateway.gateway.start()
    response = live_gateway.request(
        stream=stream,
        body={
            **request_body("canonical"),
            "max_tokens": 256,
            "stream": stream,
            "messages": [{"role": "user", "content": "Use get_weather to check the weather in Paris."}],
            "tools": [{"name": "get_weather", "description": "Get weather for a city", "parameters": CITY_SCHEMA}],
            "tool_choice": {"name": "get_weather"},
        },
    )
    assert response.status_code == 200, response.text
    if stream:
        calls = [event["delta"] for event in stream_payloads(response) if event.get("delta", {}).get("type") == "tool_call"]
        assert calls
        assert {call["name"] for call in calls if call.get("name")} == {"get_weather"}
        arguments = json.loads("".join(call.get("arguments", "") for call in calls))
    else:
        (call,) = [part for part in response.json()["content"] if part["type"] == "tool_call"]
        assert call["name"] == "get_weather"
        assert call["id"]
        arguments = json.loads(call["arguments"])
    assert isinstance(arguments, dict)
    assert set(arguments) == {"city"}
    assert isinstance(arguments["city"], str)
    assert arguments["city"].strip()
    (event,) = live_gateway.gateway.events(1)
    live_gateway.assert_metering(event)


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_live_structured_output(live_gateway: LiveGateway, stream: bool) -> None:
    live_gateway.gateway.start()
    response = live_gateway.request(
        stream=stream,
        body={
            **request_body("canonical"),
            "max_tokens": 256,
            "stream": stream,
            "messages": [{"role": "user", "content": "Return a city name in the requested JSON format."}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "city", "strict": True, "schema": CITY_SCHEMA}},
        },
    )
    assert response.status_code == 200, response.text
    output = json.loads(streamed_text("canonical", response) if stream else text_of("canonical", response))
    assert isinstance(output, dict)
    assert set(output) == {"city"}
    assert isinstance(output["city"], str)
    assert output["city"].strip()
    (event,) = live_gateway.gateway.events(1)
    live_gateway.assert_metering(event)


@pytest.mark.parametrize("family", ["anthropic"])
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_live_supported_reasoning(live_gateway: LiveGateway, stream: bool) -> None:
    live_gateway.gateway.start()
    response = live_gateway.request(
        stream=stream,
        body={
            "model": "model-a",
            "max_tokens": 1280,
            "stream": stream,
            "messages": [{"role": "user", "content": "Work out how many apples remain when 17 apples are divided into 4 equal groups."}],
            "reasoning": {"type": "enabled", "budget_tokens": 1024},
        },
    )
    assert response.status_code == 200, response.text
    if stream:
        reasoning = [event["delta"]["text"] for event in stream_payloads(response) if event.get("delta", {}).get("type") == "reasoning"]
    else:
        reasoning = [part["text"] for part in response.json()["content"] if part["type"] == "reasoning"]
    assert "".join(reasoning).strip()
    (event,) = live_gateway.gateway.events(1)
    live_gateway.assert_metering(event)
