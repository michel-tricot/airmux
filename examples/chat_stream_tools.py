"""Streaming tool calls: watch argument fragments arrive and assemble.

    uv run python examples/chat_stream_tools.py

Providers stream tool-call arguments as string fragments spread across
many events; this prints each fragment as it arrives, then the
assembled call. Assembling them is exactly what the gateway's
finalize() does server-side for accounting.
"""

from __future__ import annotations

import json
import os

import httpx
from dotenv import find_dotenv, load_dotenv

WEATHER_TOOL = {
    "name": "get_weather",
    "description": "Get the current weather for a city",
    "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string"}, "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}},
        "required": ["city"],
    },
}


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.environ.get("TOKKEEPER_INFERENCE_KEY")
    if not api_key:
        print("TOKKEEPER_INFERENCE_KEY is not set, run `uv run tokkeeper quickstart` first")
        return 1
    gateway = os.environ.get("TOKKEEPER_URL", "http://127.0.0.1:8080")
    model = os.environ.get("TOKKEEPER_MODEL", "openai/gpt-4o-mini")

    arguments: dict[int, str] = {}
    names: dict[int, str] = {}
    with httpx.stream(
        "POST",
        f"{gateway.rstrip('/')}/inf/v1/chat/completions",
        headers={"authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": "What is the weather in Paris and in Tokyo, in celsius?"}],
            "tools": [WEATHER_TOOL],
            "tool_choice": {"name": "get_weather"},
            "stream": True,
        },
        timeout=60.0,
    ) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line[len("data: ") :])
            delta = event.get("delta", {})
            if delta.get("type") == "tool_call":
                index = delta.get("index", 0)
                if delta.get("name"):
                    names[index] = delta["name"]
                    print(f"\n[tool {index}] {delta['name']}(", end="", flush=True)
                if delta.get("arguments"):
                    arguments[index] = arguments.get(index, "") + delta["arguments"]
                    print(delta["arguments"], end="", flush=True)
            elif "usage" in event:
                print(f"\n\nfinish: {event['finish_reason']} | {event['usage']['input_tokens']} in / {event['usage']['output_tokens']} out")

    print("\nassembled calls:")
    for index in sorted(names):
        print(f"  {names[index]}({json.dumps(json.loads(arguments[index]))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
