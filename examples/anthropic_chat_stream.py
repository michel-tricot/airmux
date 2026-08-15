"""Streaming chat completion from Claude, tokens printed as they arrive.

    uv run python examples/anthropic_chat_stream.py [prompt ...]

The gateway consumes Anthropic's native named-SSE stream (message_start,
content_block_delta, message_delta) and re-emits it as the same
canonical SSE a client sees for any provider. Needs ANTHROPIC_API_KEY in
.env and a bundle whose anthropic provider uses the native adapter.
"""

from __future__ import annotations

import json
import os
import sys

import httpx
from dotenv import find_dotenv, load_dotenv


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.environ.get("AIRLLM_API_KEY")
    if not api_key:
        print("AIRLLM_API_KEY is not set, run `uv run airllm quickstart` first")
        return 1
    gateway = os.environ.get("AIRLLM_URL", "http://127.0.0.1:8080")
    model = os.environ.get("AIRLLM_MODEL", "anthropic/claude-sonnet-4-6")
    prompt = " ".join(sys.argv[1:]) or "Write a short haiku about streaming data, then explain it in one line."

    with httpx.stream(
        "POST",
        f"{gateway}/v1/chat/completions",
        headers={"authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True},
        timeout=60.0,
    ) as resp:
        if resp.is_error:
            resp.read()
            print(f"http {resp.status_code}: {resp.text}")
            return 1
        for line in resp.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line[len("data: ") :])
            if event.get("delta", {}).get("type") == "text":
                print(event["delta"]["text"], end="", flush=True)
            elif "usage" in event:
                usage = event["usage"]
                print(f"\n\n[{model} | {usage['input_tokens']} in / {usage['output_tokens']} out | finish: {event['finish_reason']}]")
            elif "error" in event:
                print(f"\nstream error: {event['error']}")
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
