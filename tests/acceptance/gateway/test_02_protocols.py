from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from gateway_harness import DIALECTS, FAMILIES, PROTOCOLS, stream_payloads, streamed_text, text_of
from upstream import TEXT, UPSTREAM_KEY, Reply

if TYPE_CHECKING:
    from gateway_harness import Dialect, Gateway
    from upstream import Family


@dataclass(frozen=True)
class ProviderExpectation:
    headers: dict[str, str]
    tokens: tuple[int, int, int, int]
    costs: tuple[float, float]


PROVIDER_EXPECTATIONS: dict[Family, ProviderExpectation] = {
    "openai_compatible": ProviderExpectation({"authorization": f"Bearer {UPSTREAM_KEY}"}, (11, 3, 4, 0), (0.000015, 0.000015)),
    "openai_responses": ProviderExpectation({"authorization": f"Bearer {UPSTREAM_KEY}"}, (11, 3, 4, 0), (0.000015, 0.000015)),
    "anthropic": ProviderExpectation({"x-api-key": UPSTREAM_KEY}, (11, 3, 4, 2), (0.000016, 0.000015)),
}
STREAM_TERMINALS: dict[Dialect, tuple[str, dict[str, int]]] = {
    "openai_chat_completions": ("data: [DONE]", {}),
    "openai_responses": ("event: response.completed", {"response.completed": 1}),
    "anthropic": ("event: message_stop", {"message_stop": 1}),
}


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_every_protocol_pair_preserves_content_and_usage(gateway: Gateway, dialect: Dialect, family: Family, stream: bool):
    provider = gateway.add_provider(family)
    provider.replies["upstream-model-a"] = Reply(split_bytes=stream)
    gateway.start()
    response = gateway.request(dialect, stream=stream)
    assert response.status_code == 200, response.text
    assert (streamed_text(dialect, response) if stream else text_of(dialect, response)) == TEXT
    (received,) = provider.requests
    assert received.path == PROTOCOLS["egress"][family]
    assert received.body["model"] == "upstream-model-a"
    expected = PROVIDER_EXPECTATIONS[family]
    for header, value in expected.headers.items():
        assert received.headers[header] == value
    (event,) = gateway.events(1)
    assert (event.input_tokens, event.output_tokens, event.cache_read_tokens, event.cache_write_tokens) == expected.tokens
    assert (event.cost_input_usd, event.cost_output_usd) == pytest.approx(expected.costs, rel=1e-12, abs=1e-15)
    assert event.credential_id is not None
    assert event.credential_scope == "platform"
    assert event.stream == stream
    if stream:
        payloads = stream_payloads(response)
        assert response.headers["content-type"].startswith("text/event-stream")
        terminal_line, terminal_events = STREAM_TERMINALS[dialect]
        assert response.text.splitlines().count(terminal_line) == 1
        for event_type, count in terminal_events.items():
            assert [payload["type"] for payload in payloads].count(event_type) == count
