"""The OpenAI-compatible provider family: its JSON spelling and its transport assembly.

The spelling half is pure functions and lenient parse models, both directions. It knows no
URLs, auth or I/O, so the day a second consumer needs OpenAI's spelling (the step 5 ingress
interpretation), it splits into a shared module without touching behavior. The adapter class
at the bottom is transport only: endpoint, credential, encode."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from data_plane.adapters.base import ProviderAdapter, RawEvent, StreamState, UpstreamRequest, UpstreamStreamError, encode
from data_plane.canonical import (
    AssistantPart,
    CanonicalChunk,
    CanonicalMessage,
    CanonicalRequest,
    CanonicalResponse,
    ContentPart,
    Delta,
    FinishReason,
    ImagePart,
    NamedTool,
    Part,
    ReasoningDelta,
    ReasoningPart,
    TextDelta,
    TextPart,
    ToolCallDelta,
    ToolCallPart,
    ToolChoice,
    ToolDef,
    ToolResultPart,
    Usage,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

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
        stream=req.stream or None,
        stream_options={"include_usage": True} if req.stream else None,
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
    """OpenAI counts cache hits inside prompt_tokens, the convention canonical already uses.

    A usage block with no recognizable counts reads as absent: a provider reporting usage in an
    unknown shape must surface as an estimate, never as a free request."""
    if reported is None or (reported.prompt_tokens == 0 and reported.completion_tokens == 0):
        return Usage(estimated=True)
    return Usage(
        input_tokens=reported.prompt_tokens,
        output_tokens=reported.completion_tokens,
        cache_read_tokens=reported.prompt_tokens_details.cached_tokens,
    )


class UpstreamToolCallDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = 0
    id: str | None = None
    function: UpstreamFunction = Field(default_factory=UpstreamFunction)


class UpstreamDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[UpstreamToolCallDelta] | None = None


class UpstreamChunkChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    delta: UpstreamDelta = Field(default_factory=UpstreamDelta)
    finish_reason: str | None = None


class UpstreamChunk(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    choices: list[UpstreamChunkChoice] = Field(default_factory=list)
    usage: UpstreamUsage | None = None


@dataclass
class ToolCallDraft:
    """One tool call accreting across fragments; index-keyed in the state."""

    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class OpenAIStreamState(StreamState):
    ctx: Ctx = field(kw_only=True)
    response_id: str | None = None
    reasoning: list[str] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    tool_drafts: dict[int, ToolCallDraft] = field(default_factory=dict)
    finish: str | None = None
    usage: UpstreamUsage | None = None

    @property
    def chunk_id(self) -> str:
        return self.response_id or self.ctx.request_id


def _fold_choice(state: OpenAIStreamState, choice: UpstreamChunkChoice) -> list[CanonicalChunk]:
    """Deltas out, accumulation in: everything finalize needs folds into the state as it streams."""
    if choice.finish_reason:
        state.finish = choice.finish_reason
    deltas: list[Delta] = []
    if choice.delta.reasoning_content:
        state.reasoning.append(choice.delta.reasoning_content)
        deltas.append(ReasoningDelta(text=choice.delta.reasoning_content))
    if choice.delta.content:
        state.text.append(choice.delta.content)
        deltas.append(TextDelta(text=choice.delta.content))
    for tc in choice.delta.tool_calls or []:
        draft = state.tool_drafts.setdefault(tc.index, ToolCallDraft())
        if tc.id:
            draft.id = tc.id
        if tc.function.name:
            draft.name = tc.function.name
        draft.arguments += tc.function.arguments
        deltas.append(ToolCallDelta(index=tc.index, id=tc.id, name=tc.function.name or None, arguments=tc.function.arguments))
    return [CanonicalChunk(id=state.chunk_id, delta=delta) for delta in deltas]


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

    def new_stream_state(self, ctx: Ctx) -> OpenAIStreamState:
        return OpenAIStreamState(ctx=ctx)

    def frame(self, chunk: bytes, state: StreamState) -> Iterator[RawEvent]:
        state.buffer += chunk
        *lines, state.buffer = state.buffer.split(b"\n")
        for raw_line in lines:
            line = raw_line.rstrip(b"\r")
            if not line.startswith(b"data:"):
                continue
            data = line[len(b"data:") :].strip()
            if data == b"[DONE]":
                continue
            yield RawEvent(data=data)

    def transform_stream_event(self, ev: RawEvent, state: StreamState) -> list[CanonicalChunk]:
        assert isinstance(state, OpenAIStreamState)  # noqa: S101 state comes from new_stream_state
        data = json.loads(ev.data)
        if "error" in data:
            error = data["error"] or {}
            raise UpstreamStreamError(code=str(error.get("code") or "upstream_error"), message=str(error.get("message") or ""))
        chunk = UpstreamChunk.model_validate(data)
        if chunk.id:
            state.response_id = chunk.id
        if chunk.usage is not None:
            state.usage = chunk.usage
        return [c for choice in chunk.choices for c in _fold_choice(state, choice)]

    def finalize(self, state: StreamState) -> CanonicalResponse:
        assert isinstance(state, OpenAIStreamState)  # noqa: S101 state comes from new_stream_state
        parts: list[AssistantPart] = []
        if reasoning := "".join(state.reasoning):
            parts.append(ReasoningPart(text=reasoning))
        if text := "".join(state.text):
            parts.append(TextPart(text=text))
        parts.extend(ToolCallPart(id=draft.id, name=draft.name, arguments=draft.arguments) for _, draft in sorted(state.tool_drafts.items()))
        return CanonicalResponse(
            id=state.chunk_id,
            model=state.ctx.model.model_id,
            content=parts,
            finish_reason=finish_reason(state.finish),
            usage=usage_of(state.usage),
        )
