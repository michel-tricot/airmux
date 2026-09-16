from __future__ import annotations

from typing import TYPE_CHECKING

from gateway_harness import INFERENCE_KEY
from openai import OpenAI
from upstream import TEXT, UPSTREAM_KEY

if TYPE_CHECKING:
    from gateway_harness import Gateway


def test_the_unmodified_sdk_round_trips(gateway: Gateway) -> None:
    provider = gateway.add_provider()
    gateway.start()
    with OpenAI(base_url=gateway.url + "/inf/v1", api_key=INFERENCE_KEY) as client:
        completion = client.chat.completions.create(model="model-a", messages=[{"role": "user", "content": "hi"}])
        assert completion.choices[0].message.content == TEXT
        assert completion.usage is not None
        assert (completion.usage.prompt_tokens, completion.usage.completion_tokens) == (11, 3)
        chunks = list(client.chat.completions.create(model="model-a", messages=[{"role": "user", "content": "go"}], stream=True))
        assert "".join(chunk.choices[0].delta.content or "" for chunk in chunks if chunk.choices) == TEXT
        (usage,) = [chunk.usage for chunk in chunks if chunk.usage is not None]
        assert (usage.prompt_tokens, usage.completion_tokens) == (11, 3)
    events = gateway.events(2)
    assert [(event.status, event.stream, event.input_tokens, event.output_tokens) for event in events] == [("ok", False, 11, 3), ("ok", True, 11, 3)]
    assert all("x-tokkeeper-dialect" not in request.headers for request in provider.requests)
    assert [request.headers["authorization"] for request in provider.requests] == [f"Bearer {UPSTREAM_KEY}"] * 2
