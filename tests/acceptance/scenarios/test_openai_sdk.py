"""Acceptance: the official openai SDK, unmodified, against a running gateway.

Nothing changes but base_url and api_key: buffered and streamed completions both round-trip,
and both are metered. Step 5 of notes/design/DATAPLANE.md; the SDK's fingerprint headers are
what routes it to the OpenAI interpretation."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from openai import OpenAI

if TYPE_CHECKING:
    from conftest import Stack


def test_the_unmodified_sdk_round_trips(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

    client = OpenAI(base_url=f"{stack.dp_url}/v1", api_key=stack.caller_api_key)

    completion = client.chat.completions.create(model="echo", messages=[{"role": "user", "content": "hi"}])
    assert completion.choices[0].message.content == "ok"
    assert completion.usage is not None
    assert completion.usage.prompt_tokens == 11

    chunks = list(client.chat.completions.create(model="echo", messages=[{"role": "user", "content": "go"}], stream=True))
    text = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices and c.choices[0].delta)
    assert text == "".join(f"tick{i} " for i in range(30))
    (usage_chunk,) = [c for c in chunks if c.usage is not None]
    usage = usage_chunk.usage
    assert usage is not None
    assert usage.completion_tokens == 60

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and sum(e["status"] == "ok" for e in stack.events()) < 2:
        time.sleep(0.5)
    assert sum(e["status"] == "ok" for e in stack.events()) == 2  # both SDK calls metered
