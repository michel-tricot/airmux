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
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}, "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}},
            "required": ["city"],
        },
    },
}


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.environ.get("AIRMUX_INFERENCE_KEY")
    if not api_key:
        print("AIRMUX_INFERENCE_KEY is not set, run `uv run airmux quickstart` first")
        return 1
    gateway = os.environ.get("AIRMUX_URL", "http://127.0.0.1:8080")
    model = os.environ.get("AIRMUX_MODEL", "openai/gpt-4o-mini")

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
            "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
            "stream": True,
        },
        timeout=60.0,
    ) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line[len("data: ") :])
            for choice in event.get("choices", []):
                for tool in choice["delta"].get("tool_calls", []):
                    index = tool["index"]
                    function = tool.get("function", {})
                    if function.get("name"):
                        names[index] = function["name"]
                        print(f"\n[tool {index}] {function['name']}(", end="", flush=True)
                    if function.get("arguments"):
                        arguments[index] = arguments.get(index, "") + function["arguments"]
                        print(function["arguments"], end="", flush=True)
            if "usage" in event:
                usage = event["usage"]
                print(f"\n\nfinish: {event['gateway']['finish_reason']} | {usage['prompt_tokens']} in / {usage['completion_tokens']} out")

    print("\nassembled calls:")
    for index in sorted(names):
        print(f"  {names[index]}({json.dumps(json.loads(arguments[index]))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
