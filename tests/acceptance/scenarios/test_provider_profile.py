"""Acceptance: onboarding a quirky provider is a config change with zero code.

The quirk provider exists only in the taxonomy file: it respells max_tokens as
max_completion_tokens, closes its schema, and declares top_k as its one accepted extra. The
proof reads the wire the stub echoes back: the alias applied, the declared extra forwarded, and the
undeclared one dropped with its reason on the gateway envelope."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from conftest import Stack


def test_a_quirky_provider_onboards_as_config(stack: Stack) -> None:
    stack.write_config()
    stack.start_cp()
    stack.collect_credentials()
    stack.start_dp()
    stack.wait_dp_ready()

    response = httpx.post(
        f"{stack.dp_url}/inf/v1/chat/completions",
        headers={"authorization": f"Bearer {stack.caller_api_key}"},
        json={
            "model": "quirk",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 32,
            "top_k": 5,
            "min_p": 0.1,
        },
        timeout=10.0,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    wire = json.loads(body["content"][0]["text"])
    assert wire["max_completion_tokens"] == 32
    assert "max_tokens" not in wire
    assert wire["top_k"] == 5
    assert "min_p" not in wire

    (adjustment,) = body["gateway"]["adjustments"]
    assert (adjustment["param"], adjustment["action"]) == ("min_p", "dropped")
    assert "quirk" in adjustment["detail"]
