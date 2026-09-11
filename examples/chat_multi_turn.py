"""A three-turn conversation with visible reasoning, streamed through the gateway.

    uv run python examples/chat_multi_turn.py

Later turns depend on earlier answers, proving the history round-trips.
Reasoning renders dim; the answer renders normally. With a native
reasoning model (deepseek-reasoner and DEEPSEEK_API_KEY set) the dim
text is the model's actual reasoning stream, passed through by the
gateway as reasoning deltas. Otherwise gpt-4o-mini is asked to show its
steps, which arrive as ordinary text.

Only the answer is appended to the history: reasoning is shown, not
re-sent, which is also what native reasoning APIs require.
"""

from __future__ import annotations

import json
import os
import sys

import httpx
from dotenv import find_dotenv, load_dotenv

DIM = "\033[2m" if sys.stdout.isatty() else ""
RESET = "\033[0m" if sys.stdout.isatty() else ""

TURNS = [
    "I have 3 baskets with 7 apples each, and I buy 5 loose apples. How many apples do I have? Show your reasoning step by step.",
    "I give away a third of them, rounding down. How many are left? Reason from your previous answer.",
    "Summarize the whole calculation so far in one sentence.",
]


def run_turn(gateway: str, api_key: str, model: str, messages: list[dict]) -> str:
    answer_parts: list[str] = []
    in_reasoning = False
    with httpx.stream(
        "POST",
        f"{gateway}/v1/chat/completions",
        headers={"authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": messages, "stream": True},
        timeout=120.0,
    ) as resp:
        if resp.is_error:
            resp.read()
            print(f"http {resp.status_code}: {resp.text}")
            raise SystemExit(1)
        for line in resp.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line[len("data: ") :])
            delta = event.get("delta", {})
            if delta.get("type") == "reasoning":
                if not in_reasoning:
                    print(f"{DIM}reasoning> ", end="", flush=True)
                    in_reasoning = True
                print(delta["text"].replace("\n", f"\n{DIM}reasoning> "), end="", flush=True)
            elif delta.get("type") == "text":
                if in_reasoning:
                    print(f"{RESET}\n", flush=True)
                    in_reasoning = False
                answer_parts.append(delta["text"])
                print(delta["text"], end="", flush=True)
            elif "usage" in event:
                usage = event["usage"]
                print(f"\n{DIM}[{usage['input_tokens']} in / {usage['output_tokens']} out]{RESET}")
    return "".join(answer_parts)


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    api_key = os.environ.get("AIRLLM_INFERENCE_KEY")
    if not api_key:
        print("AIRLLM_INFERENCE_KEY is not set, run `uv run airllm quickstart` first")
        return 1
    gateway = os.environ.get("AIRLLM_URL", "http://127.0.0.1:8080")
    model = os.environ.get("AIRLLM_MODEL", "openai/gpt-4o-mini")
    native = model.startswith("deepseek-reasoner")
    print(f"model: {model} ({'native reasoning stream' if native else 'prompted step-by-step, set DEEPSEEK_API_KEY for native reasoning'})\n")

    messages: list[dict] = []
    for turn, prompt in enumerate(TURNS, start=1):
        print(f"=== turn {turn}: {prompt}\n")
        messages.append({"role": "user", "content": prompt})
        answer = run_turn(gateway, api_key, model, messages)
        messages.append({"role": "assistant", "content": answer})
        print()
    print(f"history sent on the last turn: {len(messages) - 1} messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
