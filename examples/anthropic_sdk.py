"""The official Anthropic SDK pointed at the gateway's /inf/v1/messages surface.

    uv run --with anthropic python examples/anthropic_sdk.py

Proves the gateway speaks Anthropic's Messages API well enough for the
real SDK, including its streaming helper. The model can be any provider
in the catalog: set AIRMUX_MODEL=openai/gpt-4o-mini to route an Anthropic-SDK
call to OpenAI. Needs AIRMUX_INFERENCE_KEY in .env and a running data plane.
"""

from __future__ import annotations

import os

from anthropic import Anthropic
from dotenv import find_dotenv, load_dotenv


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.environ.get("AIRMUX_INFERENCE_KEY")
    if not api_key:
        print("AIRMUX_INFERENCE_KEY is not set, run `uv run airmux quickstart` first")
        return 1
    gateway = os.environ.get("AIRMUX_URL", "http://127.0.0.1:8080")
    model = os.environ.get("AIRMUX_MODEL", "anthropic/claude-sonnet-4-6")

    client = Anthropic(base_url=f"{gateway.rstrip('/')}/inf", api_key=api_key)

    print(f"non-streaming ({model}):")
    msg = client.messages.create(model=model, max_tokens=128, messages=[{"role": "user", "content": "In one sentence, what is an LLM gateway?"}])
    print(" ", msg.content[0].text)
    print(f"  [usage: {msg.usage.input_tokens} in / {msg.usage.output_tokens} out | stop: {msg.stop_reason}]\n")

    print(f"streaming ({model}):")
    with client.messages.stream(model=model, max_tokens=128, messages=[{"role": "user", "content": "Count from 1 to 5, one per line."}]) as stream:
        for text in stream.text_stream:
            print(text, end="", flush=True)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
