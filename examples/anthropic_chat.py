"""Non-streaming chat completion routed to Claude through the native Anthropic adapter.

    uv run python examples/anthropic_chat.py [prompt ...]

Same gateway request as examples/chat.py, just a Claude model id. The
gateway translates the OpenAI-shaped request into Anthropic's Messages
API and maps the reply back to canonical shape. Needs ANTHROPIC_API_KEY
in .env and a compiled bundle whose anthropic provider uses the native
adapter (kind: anthropic).
"""

from __future__ import annotations

import os
import sys

import httpx
from dotenv import find_dotenv, load_dotenv


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    token = os.environ.get("AIRLLM_TOKEN")
    if not token:
        print("AIRLLM_TOKEN is not set, run `uv run airllm bootstrap` first")
        return 1
    gateway = os.environ.get("AIRLLM_URL", "http://127.0.0.1:8080")
    model = os.environ.get("AIRLLM_MODEL", "claude-sonnet-4-6")
    prompt = " ".join(sys.argv[1:]) or "In one sentence, what makes Claude different from other assistants?"

    resp = httpx.post(
        f"{gateway}/v1/chat/completions",
        headers={"authorization": f"Bearer {token}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=60.0,
    )
    if resp.is_error:
        print(f"http {resp.status_code}: {resp.text}")
        return 1
    data = resp.json()
    for part in data["content"]:
        if part.get("type") == "text":
            print(part["text"])
    usage = data["usage"]
    print(f"\n[{data['model']} | {usage['input_tokens']} in / {usage['output_tokens']} out | finish: {data['finish_reason']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
