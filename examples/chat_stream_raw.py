"""The streaming wire format, unparsed: every SSE line the gateway sends.

    uv run python examples/chat_stream_raw.py

Shows the Chat Completions protocol a client consumes: `data:` events,
a usage-only chunk, then the [DONE] sentinel.
"""

from __future__ import annotations

import os

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

    with httpx.stream(
        "POST",
        f"{gateway.rstrip('/')}/inf/v1/chat/completions",
        headers={"authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": [{"role": "user", "content": "Say hello in exactly three words."}], "stream": True},
        timeout=60.0,
    ) as resp:
        print(f"http {resp.status_code} {resp.headers.get('content-type')}\n")
        for line in resp.iter_lines():
            if line:
                print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
