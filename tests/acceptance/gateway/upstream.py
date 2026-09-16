from __future__ import annotations

import contextlib
import json
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

Family = Literal["openai_compatible", "openai_responses", "anthropic"]
Malformation = Literal["none", "json", "event", "event_name"]
ReportedUsage = dict[str, object] | Literal["default"] | None
UPSTREAM_KEY = "upstream-integration-secret"
TEXT = "hello 🌍"
ARGUMENTS = '{"city":"Paris"}'
DEFAULT_USAGE: dict[Family, dict[str, object]] = {
    "openai_compatible": {"prompt_tokens": 11, "completion_tokens": 3, "prompt_tokens_details": {"cached_tokens": 4}},
    "openai_responses": {"input_tokens": 11, "output_tokens": 3, "input_tokens_details": {"cached_tokens": 4}},
    "anthropic": {"input_tokens": 5, "output_tokens": 3, "cache_read_input_tokens": 4, "cache_creation_input_tokens": 2},
}


@dataclass(frozen=True)
class Reply:
    status: int = 200
    text: str = TEXT
    content: Literal["text", "tool", "reasoning"] = "text"
    usage: ReportedUsage = "default"
    terminal: bool = True
    malformed: Malformation = "none"
    delay_s: float = 0
    split_bytes: bool = False
    hold: threading.Event | None = None


@dataclass(frozen=True)
class ReceivedRequest:
    path: str
    headers: dict[str, str]
    body: dict[str, object]


def sse(event: dict[str, object]) -> bytes:
    name = event.get("type")
    prefix = f"event: {name}\n" if name else ""
    return (prefix + "data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()


def buffered(family: Family, reply: Reply) -> dict[str, object]:
    usage = DEFAULT_USAGE[family] if reply.usage == "default" else reply.usage
    if family == "openai_compatible":
        message: dict[str, object] = {"role": "assistant", "content": reply.text}
        if reply.content == "tool":
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "call-weather", "type": "function", "function": {"name": "get_weather", "arguments": ARGUMENTS}}],
            }
        if reply.content == "reasoning":
            message["reasoning_content"] = "Think carefully"
        return {
            "id": "upstream-response",
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if reply.content == "tool" else "stop"}],
            **({"usage": usage} if usage is not None else {}),
        }
    if family == "anthropic":
        content: list[dict[str, object]] = [{"type": "text", "text": reply.text}]
        if reply.content == "tool":
            content = [{"type": "tool_use", "id": "call-weather", "name": "get_weather", "input": {"city": "Paris"}}]
        if reply.content == "reasoning":
            content = [{"type": "thinking", "thinking": "Think carefully", "signature": "sig-test"}, *content]
        return {
            "id": "upstream-response",
            "type": "message",
            "role": "assistant",
            "content": content,
            "stop_reason": "tool_use" if reply.content == "tool" else "end_turn",
            **({"usage": usage} if usage is not None else {}),
        }
    output: list[dict[str, object]] = [
        {"type": "message", "id": "msg-test", "role": "assistant", "content": [{"type": "output_text", "text": reply.text}]}
    ]
    if reply.content == "tool":
        output = [{"type": "function_call", "id": "fc-test", "call_id": "call-weather", "name": "get_weather", "arguments": ARGUMENTS}]
    if reply.content == "reasoning":
        output = [{"type": "reasoning", "id": "reason-test", "summary": [{"type": "summary_text", "text": "Think carefully"}]}, *output]
    return {
        "id": "upstream-response",
        "status": "completed",
        "output": output,
        **({"usage": usage} if usage is not None else {}),
    }


def stream_events(family: Family, reply: Reply) -> list[bytes]:
    usage = DEFAULT_USAGE[family] if reply.usage == "default" else reply.usage
    if family == "openai_compatible":
        if reply.content == "tool":
            deltas = [
                {"tool_calls": [{"index": 0, "id": "call-weather", "type": "function", "function": {"name": "get_weather", "arguments": ""}}]},
                *[{"tool_calls": [{"index": 0, "function": {"arguments": part}}]} for part in ('{"city":', '"Paris"}')],
            ]
        else:
            deltas = ([{"reasoning_content": "Think carefully"}] if reply.content == "reasoning" else []) + [{"content": reply.text}]
        events = [sse({"id": "upstream-response", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}) for delta in deltas]
        events.append(sse({"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if reply.content == "tool" else "stop"}]}))
        if usage is not None:
            events.append(sse({"choices": [], "usage": usage}))
        return [*events, *([b"data: [DONE]\n\n"] if reply.terminal else [])]
    if family == "anthropic":
        opened_usage = {**usage, "output_tokens": 0} if usage is not None else {}
        events = [sse({"type": "message_start", "message": {"id": "upstream-response", "content": [], "usage": opened_usage}})]
        if reply.content == "tool":
            block = {"type": "tool_use", "id": "call-weather", "name": "get_weather", "input": {}}
            deltas = [{"type": "input_json_delta", "partial_json": part} for part in ('{"city":', '"Paris"}')]
        else:
            block = {"type": "text", "text": ""}
            deltas = [{"type": "text_delta", "text": reply.text}]
        if reply.content == "reasoning":
            events.extend(
                [
                    sse({"type": "content_block_start", "index": 1, "content_block": {"type": "thinking", "thinking": ""}}),
                    sse({"type": "content_block_delta", "index": 1, "delta": {"type": "thinking_delta", "thinking": "Think carefully"}}),
                    sse({"type": "content_block_stop", "index": 1}),
                ]
            )
        events.extend(
            [
                sse({"type": "content_block_start", "index": 2, "content_block": block}),
                *[sse({"type": "content_block_delta", "index": 2, "delta": delta}) for delta in deltas],
                sse({"type": "content_block_stop", "index": 2}),
                sse(
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "tool_use" if reply.content == "tool" else "end_turn"},
                        **({"usage": {"output_tokens": usage.get("output_tokens", 0)}} if usage is not None else {}),
                    }
                ),
            ]
        )
        return [*events, *([sse({"type": "message_stop"})] if reply.terminal else [])]
    response = buffered(family, reply)
    events = [sse({"type": "response.created", "response": {"id": "upstream-response", "status": "in_progress", "output": []}})]
    if reply.content == "tool":
        events.extend(
            [
                sse(
                    {
                        "type": "response.output_item.added",
                        "output_index": 2,
                        "item": {"type": "function_call", "call_id": "call-weather", "name": "get_weather", "arguments": ""},
                    }
                ),
                *[sse({"type": "response.function_call_arguments.delta", "output_index": 2, "delta": part}) for part in ('{"city":', '"Paris"}')],
            ]
        )
    else:
        if reply.content == "reasoning":
            events.extend(
                [
                    sse({"type": "response.output_item.added", "output_index": 0, "item": {"type": "reasoning", "id": "reason-test"}}),
                    sse({"type": "response.reasoning_summary_text.delta", "output_index": 0, "delta": "Think carefully"}),
                ]
            )
        events.append(sse({"type": "response.output_text.delta", "output_index": 1, "delta": reply.text}))
    return [*events, *([sse({"type": "response.completed", "response": response})] if reply.terminal else [])]


class ProviderHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        provider = self.server
        assert isinstance(provider, Upstream)
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        received = ReceivedRequest(self.path, {name.lower(): value for name, value in self.headers.items()}, body)
        with provider.lock:
            provider.requests.append(received)
            reply = provider.replies.get(body["model"], Reply())
            provider.capture.write_text(
                json.dumps([{"path": request.path, "body": request.body} for request in provider.requests], ensure_ascii=False)
            )
        if reply.delay_s:
            time.sleep(reply.delay_s)
        if reply.status != 200:
            error = {"code": "provider_failure", "message": f"provider rejected {UPSTREAM_KEY}"}
            if provider.family == "anthropic":
                error = {"type": "provider_failure", "message": f"provider rejected {UPSTREAM_KEY}"}
            self.respond(reply.status, json.dumps({"error": error}).encode())
            return
        if not body.get("stream"):
            self.respond(200, b"{}" if reply.malformed == "json" else json.dumps(buffered(provider.family, reply), ensure_ascii=False).encode())
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        events = stream_events(provider.family, reply)
        if reply.malformed == "event":
            events = [*events[:1], b"data: {invalid\n\n"]
        if reply.malformed == "event_name":
            events = [b"event: \xff\ndata: {}\n\n"]
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            for event in events:
                fragments = [event[index : index + 1] for index in range(len(event))] if reply.split_bytes else [event]
                for fragment in fragments:
                    self.wfile.write(fragment)
                    self.wfile.flush()
                if reply.hold is not None and b'"delta"' in event:
                    reply.hold.wait(timeout=10)

    def respond(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 parameter name is required by BaseHTTPRequestHandler
        return


class Upstream(ThreadingHTTPServer):
    def __init__(self, family: Family, capture: Path) -> None:
        super().__init__(("127.0.0.1", 0), ProviderHandler)
        self.family = family
        self.capture = capture
        self.lock = threading.Lock()
        self.requests: list[ReceivedRequest] = []
        self.replies: dict[str, Reply] = {}
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"

    def close(self) -> None:
        for reply in self.replies.values():
            if reply.hold is not None:
                reply.hold.set()
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=5)
