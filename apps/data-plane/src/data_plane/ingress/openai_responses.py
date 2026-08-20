"""OpenAI Responses ingress, including the Responses event lifecycle."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from starlette.responses import JSONResponse, Response

from data_plane.canonical import (
    Adjustment,
    CanonicalChunk,
    CanonicalMessage,
    CanonicalRequest,
    GatewayInfo,
    NamedTool,
    ReasoningConfig,
    ResponseFormat,
    TextPart,
    ToolDef,
)
from data_plane.formats import openai_responses as fmt
from data_plane.ingress.base import IngressAdapter, sse

if TYPE_CHECKING:
    from starlette.datastructures import Headers

    from data_plane.canonical import CanonicalResponse
    from data_plane.egress.base import CanonicalError, Ctx


SUPPORTED = frozenset(
    {
        "model",
        "input",
        "instructions",
        "stream",
        "max_output_tokens",
        "temperature",
        "top_p",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "reasoning",
        "text",
        "store",
        "include",
    }
)
REJECTED = frozenset(
    {"previous_response_id", "conversation", "background", "prompt", "truncation", "metadata", "service_tier", "safety_identifier", "user"}
)
SERVER_ERROR = 500


def _error(status: int, code: str, message: str) -> dict[str, Any]:
    return {"error": {"type": "invalid_request_error" if status < SERVER_ERROR else "api_error", "code": code, "message": message}}


def _mapping(value: object) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()} if isinstance(value, dict) else {}


def _reasoning(value: object) -> ReasoningConfig | None:
    raw = _mapping(value)
    summary = raw.get("summary", raw.get("generate_summary"))
    values = {
        "effort": raw.get("effort") if isinstance(raw.get("effort"), str) else None,
        "summary": summary if isinstance(summary, str) else None,
        "context": raw.get("context") if isinstance(raw.get("context"), str) else None,
        "mode": raw.get("mode") if isinstance(raw.get("mode"), str) else None,
    }
    return ReasoningConfig.model_validate(values) if any(item is not None for item in values.values()) else None


def _tools(value: object) -> list[ToolDef] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        message = "tools must be a list"
        raise TypeError(message)
    tools = []
    for raw in value:
        tool = _mapping(raw)
        if tool.get("type") != "function":
            message = "unsupported_feature: hosted tools are not supported"
            raise ValueError(message)
        tools.append(
            ToolDef(
                name=str(tool.get("name") or ""),
                description=tool.get("description") if isinstance(tool.get("description"), str) else None,
                parameters=_mapping(tool.get("parameters")),
                strict=tool.get("strict") if isinstance(tool.get("strict"), bool) else None,
            )
        )
    return tools or None


def _choice(value: object) -> object:
    choice = _mapping(value)
    if choice.get("type") == "function" and isinstance(choice.get("name"), str):
        return NamedTool(name=choice["name"])
    return value if isinstance(value, str) and value in {"auto", "none", "required"} else None


class ResponsesStream:
    def __init__(self) -> None:
        self.id = ""
        self.model = ""
        self.open_items: set[int] = set()

    def _event(self, kind: str, payload: dict[str, Any]) -> bytes:
        return b"event: " + kind.encode() + b"\n" + sse(json.dumps({"type": kind, **payload}, separators=(",", ":")).encode())

    def start(self, ctx: Ctx, /) -> list[bytes]:
        self.id, self.model = ctx.request_id, ctx.model.model_id
        response = {"id": self.id, "object": "response", "created_at": int(time.time()), "status": "in_progress", "model": self.model, "output": []}
        return [self._event("response.created", {"response": response}), self._event("response.in_progress", {"response": response})]

    def chunk(self, c: CanonicalChunk) -> list[bytes]:
        if c.delta is None:
            return []
        index = 0 if c.delta.type != "tool_call" else c.delta.index
        frames = []
        if index not in self.open_items:
            if c.delta.type == "tool_call":
                item = {
                    "type": "function_call",
                    "id": f"fc_{index}",
                    "call_id": c.delta.id or "",
                    "name": c.delta.name or "",
                    "arguments": "",
                }
            elif c.delta.type == "reasoning":
                item = {
                    "type": "reasoning",
                    "id": c.delta.id or f"rs_{index}",
                    "summary": [],
                    **({"encrypted_content": c.delta.data} if c.delta.data else {}),
                }
            else:
                item = {"type": "message", "id": f"msg_{index}", "role": "assistant", "status": "in_progress", "content": []}
            frames.append(self._event("response.output_item.added", {"output_index": index, "item": item}))
            self.open_items.add(index)
        if c.delta.type == "text":
            frames.append(self._event("response.output_text.delta", {"output_index": index, "content_index": 0, "delta": c.delta.text}))
        elif c.delta.type == "reasoning":
            if c.delta.text:
                frames.append(
                    self._event("response.reasoning_summary_text.delta", {"output_index": index, "summary_index": 0, "delta": c.delta.text})
                )
        else:
            frames.append(self._event("response.function_call_arguments.delta", {"output_index": index, "delta": c.delta.arguments}))
        return frames

    def closing(self, final: CanonicalResponse, adjustments: list[Adjustment]) -> list[bytes]:
        frames = [
            self._event("response.output_item.done", {"output_index": index, "item": {"id": f"item_{index}", "status": "completed"}})
            for index in sorted(self.open_items)
        ]
        response = fmt.json_response(final.id, final.model, final.content, final.finish_reason, final.usage)
        response["gateway"] = GatewayInfo(adjustments=adjustments).model_dump(mode="json")
        frames.append(self._event("response.completed", {"response": response}))
        return frames

    def error(self, err: CanonicalError) -> list[bytes]:
        return [self._event("error", _error(err.status, err.code, err.message))]


class OpenAIResponsesIngress(IngressAdapter):
    dialect = "openai_responses"

    def claims(self, headers: Headers, body: dict[str, Any], /) -> bool:
        return headers.get("user-agent", "").startswith("OpenAI/") and "input" in body

    def parse(self, body: dict[str, Any]) -> tuple[CanonicalRequest, list[Adjustment]]:
        unsupported = sorted(set(body) - SUPPORTED)
        if unsupported:
            message = f"unsupported_feature: {', '.join(unsupported)}"
            raise ValueError(message)
        if body.get("store") not in {None, False}:
            message = "unsupported_feature: store=true is not supported"
            raise ValueError(message)
        include = body.get("include")
        allowed_include = (None, [], ["reasoning.encrypted_content"])
        if include not in allowed_include:
            message = "unsupported_feature: include is not supported"
            raise ValueError(message)
        input_value = body.get("input")
        if isinstance(input_value, str):
            messages = fmt.messages_of([{"type": "message", "role": "user", "content": [{"type": "input_text", "text": input_value}]}])
        else:
            messages = fmt.messages_of(input_value)
        if instructions := body.get("instructions"):
            if not isinstance(instructions, str):
                message = "instructions must be a string"
                raise ValueError(message)
            messages.insert(0, CanonicalMessage(role="system", content=[TextPart(text=instructions)]))
        text = _mapping(body.get("text"))
        response_format = ResponseFormat.model_validate(text["format"]) if isinstance(text.get("format"), dict) else None
        request = CanonicalRequest(
            model=str(body.get("model") or ""),
            messages=messages,
            stream=bool(body.get("stream")),
            max_tokens=body.get("max_output_tokens"),
            temperature=body.get("temperature"),
            top_p=body.get("top_p"),
            tools=_tools(body.get("tools")),
            tool_choice=_choice(body.get("tool_choice")),
            parallel_tool_calls=body.get("parallel_tool_calls") if isinstance(body.get("parallel_tool_calls"), bool) else None,
            reasoning=_reasoning(body.get("reasoning")),
            response_format=response_format,
        )
        return request, []

    def render_response(self, final: CanonicalResponse) -> Response:
        body = fmt.json_response(final.id, final.model, final.content, final.finish_reason, final.usage)
        body["gateway"] = final.gateway.model_dump(mode="json")
        return JSONResponse(body)

    def render_error(self, err: CanonicalError) -> Response:
        return JSONResponse(_error(err.status, err.code, err.message), status_code=err.status)

    def new_stream(self) -> ResponsesStream:
        return ResponsesStream()
