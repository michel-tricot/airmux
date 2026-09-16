"""Non-streaming chat completion through the gateway.

    uv run python examples/chat.py [prompt ...]

Reads AIRMUX_INFERENCE_KEY from .env (run `airmux quickstart` to mint one).
Override the defaults with AIRMUX_URL and AIRMUX_MODEL env vars.
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
    model = os.environ.get("AIRMUX_MODEL", "openai/gpt-4o-mini")
    prompt = " ".join(sys.argv[1:]) or "Say hi and share one fun fact."

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
