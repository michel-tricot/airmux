from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.acceptance.gateway.gateway_harness import FAMILIES, streamed_text, text_of

if TYPE_CHECKING:
    from live_harness import LiveGateway


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("stream", [False, True], ids=["buffered", "stream"])
def test_live_completion_and_native_usage(live_gateway: LiveGateway, stream: bool) -> None:
    live_gateway.gateway.start()
    response = live_gateway.request(stream=stream)
    assert response.status_code == 200, response.text
    text = streamed_text("openai_chat_completions", response) if stream else text_of("openai_chat_completions", response)
    assert text.strip()
    if stream:
        assert response.text.splitlines().count("data: [DONE]") == 1
    (event,) = live_gateway.gateway.events(1)
    assert event.stream == stream
    live_gateway.assert_metering(event)
