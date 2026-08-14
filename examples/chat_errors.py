"""Every way a request can fail, and what the gateway returns for each.

    uv run python examples/chat_errors.py

Each scenario prints the HTTP status and body. Note that errors on a
stream=true request still come back as plain JSON when they happen
before the stream starts.
"""

from __future__ import annotations

import os

import httpx
from dotenv import find_dotenv, load_dotenv


def show(name: str, resp: httpx.Response) -> None:
    print(f"\n=== {name}")
    print(f"    http {resp.status_code}: {resp.text[:200]}")


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.environ.get("AIRLLM_API_KEY", "")
    gateway = os.environ.get("AIRLLM_URL", "http://127.0.0.1:8080")
    url = f"{gateway}/v1/chat/completions"
    auth = {"authorization": f"Bearer {api_key}"}
    messages = [{"role": "user", "content": "hi"}]

    show(
        "invalid api key -> 401 from the gateway",
        httpx.post(url, headers={"authorization": "Bearer not-a-jwt"}, json={"model": "gpt-4o-mini", "messages": messages}),
    )

    show("unknown model -> 404 from policy", httpx.post(url, headers=auth, json={"model": "no-such-model", "messages": messages}))

    show("malformed body -> 400 from validation", httpx.post(url, headers=auth, json={"messages": "not-a-list"}))

    show(
        "stream=true with unknown model -> still a JSON error, no SSE",
        httpx.post(url, headers=auth, json={"model": "no-such-model", "messages": messages, "stream": True}),
    )

    show(
        "upstream rejection passes through -> OpenAI's own 400",
        httpx.post(url, headers=auth, json={"model": "gpt-4o-mini", "messages": messages, "max_tokens": 10_000_000}, timeout=30.0),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
