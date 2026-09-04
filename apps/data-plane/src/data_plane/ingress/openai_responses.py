"""OpenAI Responses ingress, including the Responses event lifecycle."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from starlette.responses import JSONResponse, Response

from data_plane.canonical import (
    CanonicalAdjustment,
    CanonicalChunk,
    CanonicalGatewayInfo,
    CanonicalJsonObjectResponseFormat,
    CanonicalJsonSchemaResponseFormat,
    CanonicalNamedTool,
    CanonicalReasoningConfig,
    CanonicalRequest,
    CanonicalResponseFormat,
    CanonicalSystemMessage,
    CanonicalTextPart,
    CanonicalTextResponseFormat,
    CanonicalToolDef,
)
from data_plane.errors import UnsupportedFeatureError
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
SERVER_ERROR = 500


def _error(status: int, code: str, message: str) -> dict[str, Any]:
    return {"error": {"type": "invalid_request_error" if status < SERVER_ERROR else "api_error", "code": code, "message": message}}


def _mapping(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        message = "expected a JSON object"
        raise TypeError(message)
    if any(not isinstance(key, str) for key in value):
        message = "JSON object keys must be strings"
        raise TypeError(message)
    return cast("dict[str, Any]", value)


def _tools(value: object) -> list[CanonicalToolDef] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        message = "tools must be a list"
        raise TypeError(message)
    tools = []
    for raw in value:
        tool = _mapping(raw)
        if tool.get("type") != "function":
            message = "hosted tools are not supported"
            raise UnsupportedFeatureError(message)
        tools.append(
            CanonicalToolDef.model_validate(
                {
                    "name": tool.get("name"),
                    "description": tool.get("description"),
                    "parameters": _mapping(tool.get("parameters")),
                    "strict": tool.get("strict"),
                }
            )
        )
    return tools or None


def _choice(value: object) -> object:
    if value is None or (isinstance(value, str) and value in {"auto", "none", "required"}):
        return value
    choice = _mapping(value)
    if choice.get("type") == "function" and isinstance(choice.get("name"), str):
        return CanonicalNamedTool(name=choice["name"])
    message = "unsupported tool_choice"
    raise UnsupportedFeatureError(message)


def _response_format(value: object) -> CanonicalResponseFormat | None:
    if value is None:
        return None
    format_value = _mapping(value)
    kind = format_value.get("type")
    if kind == "json_schema":
        return CanonicalJsonSchemaResponseFormat(json_schema={key: item for key, item in format_value.items() if key != "type"})
    if kind == "text":
        return CanonicalTextResponseFormat()
    if kind == "json_object":
        return CanonicalJsonObjectResponseFormat()
    message = "unsupported text format"
    raise UnsupportedFeatureError(message)


@dataclass
class _ResponseItem:
    output_index: int
    kind: str
    item_id: str
    call_id: str = ""
    name: str = ""
    text: str = ""
    arguments: str = ""
    signature: str = ""

    def body(self, status: str) -> dict[str, Any]:
        if self.kind == "message":
            content = [] if status == "in_progress" else [{"type": "output_text", "text": self.text, "annotations": []}]
            return {"type": "message", "id": self.item_id, "role": "assistant", "status": status, "content": content}
        if self.kind == "reasoning":
            summary = [] if not self.text else [{"type": "summary_text", "text": self.text}]
            return {
                "type": "reasoning",
                "id": self.item_id,
                "summary": summary,
                **({"encrypted_content": self.signature} if self.signature else {}),
            }
        return {
            "type": "function_call",
            "id": self.item_id,
            "call_id": self.call_id,
            "name": self.name,
            "arguments": self.arguments,
            "status": status,
        }


class ResponsesStream:
    def __init__(self) -> None:
        self.id = ""
        self.model = ""
        self.created_at = 0
        self.sequence = 0
        self.items: dict[tuple[str, int], _ResponseItem] = {}

    def _event(self, kind: str, payload: dict[str, Any]) -> bytes:
        body = {"type": kind, **payload, "sequence_number": self.sequence}
        self.sequence += 1
        return b"event: " + kind.encode() + b"\n" + sse(json.dumps(body, separators=(",", ":")).encode())

    def start(self, ctx: Ctx, /) -> list[bytes]:
        self.id, self.model, self.created_at = str(ctx.request_id), ctx.model.model_id, int(time.time())
        metadata = fmt.ResponseMetadata(id=self.id, model=self.model, created_at=self.created_at)
        response = {**fmt.response_metadata(metadata), "status": "in_progress", "output": []}
        return [self._event("response.created", {"response": response}), self._event("response.in_progress", {"response": response})]

    def chunk(self, c: CanonicalChunk) -> list[bytes]:
        delta = c.delta
        if delta is None:
            return []
        ordinal = delta.index if delta.type == "tool_call" else 0
        key = (delta.type, ordinal)
        frames = []
        item = self.items.get(key)
        opened = item is None
        if item is None:
            index = len(self.items)
            if delta.type == "tool_call":
                item = _ResponseItem(index, "function_call", f"fc_{index}", call_id=delta.id or "", name=delta.name or "")
            elif delta.type == "reasoning":
                item = _ResponseItem(index, "reasoning", delta.id or f"rs_{index}", signature=delta.signature or "")
            else:
                item = _ResponseItem(index, "message", f"msg_{index}")
            self.items[key] = item
            frames.append(self._event("response.output_item.added", {"output_index": index, "item": item.body("in_progress")}))
        if delta.type == "text":
            item.text += delta.text
            frames.append(
                self._event(
                    "response.output_text.delta",
                    {"item_id": item.item_id, "output_index": item.output_index, "content_index": 0, "delta": delta.text, "logprobs": []},
                )
            )
        elif delta.type == "reasoning":
            item.text += delta.text
            if not opened:
                item.signature += delta.signature or ""
            if delta.text:
                frames.append(
                    self._event(
                        "response.reasoning_summary_text.delta",
                        {"item_id": item.item_id, "output_index": item.output_index, "summary_index": 0, "delta": delta.text},
                    )
                )
        else:
            item.call_id = delta.id or item.call_id
            item.name = delta.name or item.name
            item.arguments += delta.arguments
            if delta.arguments:
                frames.append(
                    self._event(
                        "response.function_call_arguments.delta",
                        {"item_id": item.item_id, "output_index": item.output_index, "delta": delta.arguments},
                    )
                )
        return frames

    def closing(self, final: CanonicalResponse, adjustments: list[CanonicalAdjustment]) -> list[bytes]:
        ordered = sorted(self.items.values(), key=lambda item: item.output_index)
        frames = [self._event("response.output_item.done", {"output_index": item.output_index, "item": item.body("completed")}) for item in ordered]
        metadata = fmt.ResponseMetadata(id=final.id, model=final.model, created_at=self.created_at)
        response = fmt.json_response(metadata, final.content, final.finish_reason, final.usage)
        response["gateway"] = CanonicalGatewayInfo(finish_reason=final.finish_reason, adjustments=adjustments).model_dump(mode="json")
        frames.append(self._event("response.completed", {"response": response}))
        return frames

    def error(self, err: CanonicalError) -> list[bytes]:
        return [self._event("error", {"code": err.code, "message": err.message, "param": None})]


class OpenAIResponsesIngress(IngressAdapter):
    dialect = "openai_responses"

    def claims(self, headers: Headers, body: dict[str, Any], /) -> bool:
        return headers.get("user-agent", "").startswith("OpenAI/") and "input" in body

    def parse(self, body: dict[str, Any]) -> tuple[CanonicalRequest, list[CanonicalAdjustment]]:
        unsupported = sorted(set(body) - SUPPORTED)
        if unsupported:
            message = ", ".join(unsupported)
            raise UnsupportedFeatureError(message)
        if body.get("store") is not None and body["store"] is not False:
            message = "only store=false is supported"
            raise UnsupportedFeatureError(message)
        include = body.get("include")
        allowed_include = (None, [], ["reasoning.encrypted_content"])
        if include not in allowed_include:
            message = "include is not supported"
            raise UnsupportedFeatureError(message)
        input_value = body.get("input")
        if isinstance(input_value, str):
            messages = fmt.messages_of([{"type": "message", "role": "user", "content": [{"type": "input_text", "text": input_value}]}])
        else:
            messages = fmt.messages_of(input_value)
        if (instructions := body.get("instructions")) is not None:
            if not isinstance(instructions, str):
                message = "instructions must be a string"
                raise ValueError(message)
            messages.insert(0, CanonicalSystemMessage(content=[CanonicalTextPart(text=instructions)]))
        text = _mapping(body.get("text"))
        response_format = _response_format(text.get("format"))
        reasoning = _mapping(body.get("reasoning"))
        request = CanonicalRequest.model_validate(
            {
                "model": body.get("model"),
                "messages": messages,
                "stream": body.get("stream", False),
                "max_tokens": body.get("max_output_tokens"),
                "temperature": body.get("temperature"),
                "top_p": body.get("top_p"),
                "tools": _tools(body.get("tools")),
                "tool_choice": _choice(body.get("tool_choice")),
                "parallel_tool_calls": body.get("parallel_tool_calls"),
                "reasoning": CanonicalReasoningConfig.model_validate(reasoning) if reasoning else None,
                "response_format": response_format,
            }
        )
        return request, []

    def render_response(self, final: CanonicalResponse) -> Response:
        metadata = fmt.ResponseMetadata(id=final.id, model=final.model, created_at=int(time.time()))
        body = fmt.json_response(metadata, final.content, final.finish_reason, final.usage)
        body["gateway"] = final.gateway.model_dump(mode="json")
        return JSONResponse(body)

    def render_error(self, err: CanonicalError) -> Response:
        return JSONResponse(_error(err.status, err.code, err.message), status_code=err.status)

    def new_stream(self) -> ResponsesStream:
        return ResponsesStream()
