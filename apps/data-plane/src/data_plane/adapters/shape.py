from __future__ import annotations

from typing import Any


def content_blocks(reasoning: str, text: str, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The one definition of canonical response content, shared by every adapter.

    Order is reasoning, then text, then tool calls; empty parts are omitted so
    the streaming and non-streaming paths of any adapter agree.
    """
    reasoning_part = [{"type": "reasoning", "text": reasoning}] if reasoning else []
    text_part = [{"type": "text", "text": text}] if text else []
    tool_part = [{"type": "tool_call", "id": tc.get("id"), "function": tc.get("function") or {}} for tc in tool_calls]
    return [*reasoning_part, *text_part, *tool_part]
