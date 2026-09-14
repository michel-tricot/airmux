"""Streaming chat completion through the gateway, tokens printed as they arrive.

    uv run python examples/chat_stream.py [prompt ...]

Reads TOKKEEPER_INFERENCE_KEY from .env (run `tokkeeper quickstart` to mint one).
Override the defaults with TOKKEEPER_URL and TOKKEEPER_MODEL env vars.
"""

from __future__ import annotations

import json
import os
import sys

import httpx
from dotenv import find_dotenv, load_dotenv


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.environ.get("TOKKEEPER_INFERENCE_KEY")
    if not api_key:
        print("TOKKEEPER_INFERENCE_KEY is not set, run `uv run tokkeeper quickstart` first")
        return 1
    gateway = os.environ.get("TOKKEEPER_URL", "http://127.0.0.1:8080")
    model = os.environ.get("TOKKEEPER_MODEL", "openai/gpt-4o-mini")
    prompt = " ".join(sys.argv[1:]) or "Count from 1 to 10, then say something encouraging."

    with httpx.stream(
        "POST",
        f"{gateway.rstrip('/')}/inf/v1/chat/completions",
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
