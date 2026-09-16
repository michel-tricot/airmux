"""Abandon a stream mid-flight and let the gateway account for it.

    uv run python examples/chat_stream_cancel.py

Takes the first few tokens then closes the connection. The gateway
closes the upstream socket, finalizes the partial response, and records
a usage event with status=cancelled; watch the data plane console
(running with --dev) to see it.
"""

from __future__ import annotations

import json
import os

import httpx
from dotenv import find_dotenv, load_dotenv

TAKE = 5


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.environ.get("AIRMUX_INFERENCE_KEY")
    if not api_key:
        print("AIRMUX_INFERENCE_KEY is not set, run `uv run airmux quickstart` first")
        return 1
    gateway = os.environ.get("AIRMUX_URL", "http://127.0.0.1:8080")
    model = os.environ.get("AIRMUX_MODEL", "openai/gpt-4o-mini")

    seen = 0
    with httpx.stream(
        "POST",
        f"{gateway.rstrip('/')}/inf/v1/chat/completions",
        headers={"authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": [{"role": "user", "content": "Count from 1 to 200, one number per line."}], "stream": True},
        timeout=60.0,
    ) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line[len("data: ") :])
            if event.get("delta", {}).get("type") == "text":
                print(event["delta"]["text"], end="", flush=True)
                seen += 1
                if seen >= TAKE:
                    break

    print(f"\n\nclosed the connection after {TAKE} deltas.")
    print("the data plane console (dev mode) now shows a status=cancelled usage record with partial counts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
