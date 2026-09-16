"""Non-streaming chat completion routed to Claude through the native Anthropic adapter.

    uv run python examples/anthropic_chat.py [prompt ...]

Same Chat Completions request as examples/chat.py, just a Claude model id. The
gateway translates the request into Anthropic's Messages
API and maps the reply back to Chat Completions. Needs ANTHROPIC_API_KEY
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
    api_key = os.environ.get("AIRMUX_INFERENCE_KEY")
    if not api_key:
        print("AIRMUX_INFERENCE_KEY is not set, run `uv run airmux quickstart` first")
        return 1
    gateway = os.environ.get("AIRMUX_URL", "http://127.0.0.1:8080")
    model = os.environ.get("AIRMUX_MODEL", "anthropic/claude-sonnet-4-6")
    prompt = " ".join(sys.argv[1:]) or "In one sentence, what makes Claude different from other assistants?"

    resp = httpx.post(
        f"{gateway.rstrip('/')}/inf/v1/chat/completions",
        headers={"authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=60.0,
    )
    if resp.is_error:
        print(f"http {resp.status_code}: {resp.text}")
        return 1
    data = resp.json()
    choice = data["choices"][0]
    print(choice["message"]["content"])
    usage = data["usage"]
    print(f"\n[{data['model']} | {usage['prompt_tokens']} in / {usage['completion_tokens']} out | finish: {choice['finish_reason']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
