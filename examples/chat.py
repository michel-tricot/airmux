"""Non-streaming chat completion through the gateway.

    uv run python examples/chat.py [prompt ...]

Reads AIRLLM_TOKEN from .env (run `airllm bootstrap` to mint one).
Override the defaults with AIRLLM_URL and AIRLLM_MODEL env vars.
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
    model = os.environ.get("AIRLLM_MODEL", "gpt-4o-mini")
    prompt = " ".join(sys.argv[1:]) or "Say hi and share one fun fact."

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
