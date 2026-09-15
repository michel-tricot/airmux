from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from gateway_harness import DIALECTS, FAMILIES, PROTOCOLS, stream_payloads, streamed_text, text_of
from upstream import TEXT, UPSTREAM_KEY, Reply

if TYPE_CHECKING:
    from gateway_harness import Dialect, Gateway
    from upstream import Family


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
    assert received.headers["x-api-key" if family == "anthropic" else "authorization"] == (
        UPSTREAM_KEY if family == "anthropic" else f"Bearer {UPSTREAM_KEY}"
    )
    (event,) = gateway.events(1)
    assert (event.input_tokens, event.output_tokens, event.cache_read_tokens, event.cache_write_tokens) == (
        11,
        3,
        4,
        2 if family == "anthropic" else 0,
    )
    assert event.cost_input_usd == pytest.approx(0.000016 if family == "anthropic" else 0.000015)
    assert event.cost_output_usd == pytest.approx(0.000015)
    assert event.credential_id is not None
    assert event.credential_scope == "platform"
    assert event.stream == stream
    if stream:
        payloads = stream_payloads(response)
        assert response.headers["content-type"].startswith("text/event-stream")
        if dialect in ("canonical", "openai_native"):
            assert response.text.splitlines().count("data: [DONE]") == 1
        elif dialect == "anthropic":
            assert [payload["type"] for payload in payloads].count("message_stop") == 1
        else:
            assert [payload["type"] for payload in payloads].count("response.completed") == 1
