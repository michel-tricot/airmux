"""The OpenAI-compatible provider family: its JSON spelling and its transport assembly.

The spelling half is pure functions and lenient parse models, both directions. It knows no
URLs, auth or I/O, so the day a second consumer needs OpenAI's spelling (the step 5 ingress
interpretation), it splits into a shared module without touching behavior. The adapter class
at the bottom is transport only: endpoint, credential, encode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from data_plane.adapters.base import ProviderAdapter, UpstreamRequest, encode
from data_plane.canonical import (
    AssistantPart,
    CanonicalMessage,
    CanonicalRequest,
    CanonicalResponse,
    ContentPart,
    FinishReason,
    ImagePart,
    NamedTool,
    Part,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolChoice,
    ToolDef,
    ToolResultPart,
    Usage,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from contract import ModelEntry
    from data_plane.adapters.base import Ctx

DATA_URL = "data:"


class ChatBody(BaseModel):
    """Every field the gateway can put on an OpenAI chat request. Absent means None, so the omission
    rule is a property of the type rather than a filter at the call site."""

    model_config = ConfigDict(frozen=True)

    model: str
    messages: list[dict[str, Any]]
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: list[str] | None = None
    seed: int | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    stream: bool | None = None
    stream_options: dict[str, Any] | None = None


def _image_to_url(part: ImagePart) -> str:
    return part.url if part.url is not None else f"{DATA_URL}{part.media_type};base64,{part.data}"


def _text_of_parts(parts: Sequence[Part]) -> str:
    return "".join(part.text for part in parts if isinstance(part, TextPart))


def _user_content(parts: Sequence[ContentPart]) -> str | list[dict[str, Any]]:
    if all(isinstance(part, TextPart) for part in parts):
        return _text_of_parts(parts)
    blocks: list[dict[str, Any]] = []
    for part in parts:
        if isinstance(part, TextPart):
            blocks.append({"type": "text", "text": part.text})
        elif isinstance(part, ImagePart):
            blocks.append({"type": "image_url", "image_url": {"url": _image_to_url(part)}})
    return blocks


def _assistant_message(parts: Sequence[ContentPart]) -> dict[str, Any]:
    calls = [part for part in parts if isinstance(part, ToolCallPart)]
    message: dict[str, Any] = {"role": "assistant", "content": _text_of_parts(parts) or None}
    if calls:
        message["tool_calls"] = [{"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}} for call in calls]
    return message


def to_messages(messages: Sequence[CanonicalMessage]) -> list[dict[str, Any]]:
    """Canonical into OpenAI's wire messages. Tool result parts expand back into their own tool
    messages, and reasoning is dropped: OpenAI does not accept it back on a later turn."""
    out: list[dict[str, Any]] = []
    for message in messages:
        results = [part for part in message.content if isinstance(part, ToolResultPart)]
        rest: list[ContentPart] = [part for part in message.content if not isinstance(part, ToolResultPart)]
        out.extend({"role": "tool", "tool_call_id": result.call_id, "content": _text_of_parts(result.content)} for result in results)
        if not rest:
            continue
        if message.role == "system":
            out.append({"role": "system", "content": _text_of_parts(rest)})
        elif message.role == "assistant":
            out.append(_assistant_message(rest))
        else:
            out.append({"role": "user", "content": _user_content(rest)})
    return out


def to_tools(tools: Sequence[ToolDef] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {"name": tool.name, **({"description": tool.description} if tool.description else {}), "parameters": tool.parameters},
        }
        for tool in tools
    ]


def to_tool_choice(choice: ToolChoice | None) -> str | dict[str, Any] | None:
    if choice is None:
        return None
    if isinstance(choice, NamedTool):
        return {"type": "function", "function": {"name": choice.name}}
    return choice


def body_of(req: CanonicalRequest, upstream_model: str) -> ChatBody:
    """The one place canonical becomes an OpenAI chat body, every field mapped by hand.

    A name matching across the two schemas is coincidence, not a rule: this list is where a
    provider's spelling differences and profile-driven aliases apply, so it never gets replaced
    by a reflective copy."""
    return ChatBody(
        model=upstream_model,
        messages=to_messages(req.messages),
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        top_p=req.top_p,
        stop=req.stop,
        seed=req.seed,
        tools=to_tools(req.tools),
        tool_choice=to_tool_choice(req.tool_choice),
        response_format=req.response_format.model_dump(exclude_none=True) if req.response_format else None,
    )


# What comes back. Lenient where providers differ: a missing field degrades to a default
# rather than failing the response.


class UpstreamFunction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    arguments: str = ""


class UpstreamToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    function: UpstreamFunction = Field(default_factory=UpstreamFunction)


class UpstreamMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[UpstreamToolCall] | None = None


class UpstreamChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: UpstreamMessage = Field(default_factory=UpstreamMessage)
    finish_reason: str | None = None


class UpstreamTokenDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cached_tokens: int = 0


class UpstreamUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_tokens_details: UpstreamTokenDetails = Field(default_factory=UpstreamTokenDetails)


class UpstreamCompletion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    choices: list[UpstreamChoice] = Field(default_factory=list)
    usage: UpstreamUsage | None = None


FINISH_REASONS: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "content_filter": "content_filter",
}


def finish_reason(raw: str | None) -> FinishReason | None:
    """A buffered response always finished; an unrecognized provider spelling reads as a plain stop."""
    if raw is None:
        return None
    return FINISH_REASONS.get(raw, "stop")


def response_parts(message: UpstreamMessage) -> list[AssistantPart]:
    """Order is reasoning, then text, then tool calls; empty parts are omitted so the streaming and
    non-streaming paths agree once both exist."""
    parts: list[AssistantPart] = []
    if message.reasoning_content:
        parts.append(ReasoningPart(text=message.reasoning_content))
    if message.content:
        parts.append(TextPart(text=message.content))
    parts.extend(ToolCallPart(id=call.id, name=call.function.name, arguments=call.function.arguments) for call in message.tool_calls or [])
    return parts


def usage_of(reported: UpstreamUsage | None) -> Usage:
    """OpenAI counts cache hits inside prompt_tokens, the convention canonical already uses."""
    if reported is None:
        return Usage(estimated=True)
    return Usage(
        input_tokens=reported.prompt_tokens,
        output_tokens=reported.completion_tokens,
        cache_read_tokens=reported.prompt_tokens_details.cached_tokens,
    )


class OpenAICompatibleAdapter(ProviderAdapter):
    kind = "openai_compatible"

    def transform_request(self, req: CanonicalRequest, m: ModelEntry) -> UpstreamRequest:
        """Transport assembly only; every field mapping lives in body_of."""
        headers = {
            "authorization": f"Bearer {self.credential.reveal()}",
            "content-type": "application/json",
        }
        url = str(self.provider.base_url).rstrip("/") + "/chat/completions"
        return UpstreamRequest(method="POST", url=url, headers=headers, body=encode(body_of(req, m.upstream_model)))

    def transform_response(self, raw: bytes, ctx: Ctx) -> CanonicalResponse:
        completion = UpstreamCompletion.model_validate_json(raw)
        choice = completion.choices[0] if completion.choices else UpstreamChoice()
        return CanonicalResponse(
            id=completion.id or ctx.request_id,
            model=ctx.model.model_id,
            content=response_parts(choice.message),
            finish_reason=finish_reason(choice.finish_reason),
            usage=usage_of(completion.usage),
        )
