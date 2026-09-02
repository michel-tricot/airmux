"""The completion definition the gateway owns.

Requests arrive in this shape, responses and stream chunks leave in it; adapters translate
outward to whatever the upstream provider speaks. The three faces (request, response, stream)
are published as JSON Schema into taxonomy/schemas/completion via `airllmdp schema`, where they
sit beside the provider schemas they are translated into.

The request is open at the top level: a caller who swapped a provider's base URL for the
gateway may carry fields the core does not model. Those are captured for forwarding, and every
one the gateway drops or changes on the way upstream is reported under the response's gateway
field, never silently. Nested shapes (messages, parts, tools) stay closed: they are
restructured in translation, so an unknown field there has nothing faithful to forward.

One input shorthand exists: a message's content may be a plain string, normalized to a single
text part at the edge. Everything stored, translated or emitted is the typed form.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, model_validator

WIRE = ConfigDict(frozen=True, extra="forbid")


class Part(BaseModel):
    """One piece of a message. cache marks a prompt-cache breakpoint after this part, honored by
    providers that take explicit breakpoints and ignored by providers that cache on their own."""

    model_config = WIRE

    cache: Literal["ephemeral"] | None = None


class TextPart(Part):
    type: Literal["text"] = "text"
    text: str


class ImagePart(Part):
    """An image by reference or by value; exactly one of url or data is set."""

    type: Literal["image"] = "image"
    url: str | None = None
    data: str | None = None  # base64, no data: prefix
    media_type: str | None = None  # required alongside data, absent for a url the provider fetches itself

    @model_validator(mode="after")
    def one_source(self) -> ImagePart:
        if (self.url is None) == (self.data is None):
            msg = "image part needs exactly one of url or data"
            raise ValueError(msg)
        if self.data is not None and not self.media_type:
            msg = "inline image data needs a media_type"
            raise ValueError(msg)
        return self


class DocumentPart(Part):
    type: Literal["document"] = "document"
    filename: str | None = None
    url: str | None = None
    data: str | None = None
    file_id: str | None = None
    media_type: str | None = None

    @model_validator(mode="after")
    def one_source(self) -> DocumentPart:
        if sum(source is not None for source in (self.url, self.data, self.file_id)) != 1:
            msg = "document part needs exactly one of url, data or file_id"
            raise ValueError(msg)
        if self.data is not None and not self.media_type:
            msg = "inline document data needs a media_type"
            raise ValueError(msg)
        return self


class ReasoningPart(Part):
    """Model reasoning. signature is an opaque provider token: a provider that issues one rejects a
    later turn whose reasoning comes back without it."""

    type: Literal["reasoning"] = "reasoning"
    id: str | None = None
    text: str
    signature: str | None = None


class ToolCallPart(Part):
    """A tool invocation. arguments stays JSON text: parsing it loses a truncated stream's partial
    arguments and re-serializing changes the key order the provider chose."""

    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: str


ToolResultContent = Annotated[TextPart | ImagePart, Field(discriminator="type")]


def _text_shorthand(content: object) -> object:
    """A plain string is shorthand for a single text part; the typed form is the only one stored or emitted."""
    return [{"type": "text", "text": content}] if isinstance(content, str) else content


class ToolResultPart(Part):
    """The outcome of a tool call, carried as a user part rather than as its own role."""

    type: Literal["tool_result"] = "tool_result"
    call_id: str
    content: Annotated[list[ToolResultContent], BeforeValidator(_text_shorthand, json_schema_input_type=list[ToolResultContent] | str)]
    is_error: bool = False


ContentPart = Annotated[
    TextPart | ImagePart | DocumentPart | ReasoningPart | ToolCallPart | ToolResultPart,
    Field(discriminator="type"),
]

AssistantPart = Annotated[TextPart | ReasoningPart | ToolCallPart, Field(discriminator="type")]

Role = Literal["system", "user", "assistant"]

ALLOWED_PARTS: dict[Role, frozenset[str]] = {
    "system": frozenset({"text"}),
    "user": frozenset({"text", "image", "document", "tool_result"}),
    "assistant": frozenset({"text", "reasoning", "tool_call"}),
}


class CanonicalMessage(BaseModel):
    model_config = WIRE

    role: Role
    content: Annotated[list[ContentPart], BeforeValidator(_text_shorthand, json_schema_input_type=list[ContentPart] | str)]

    @model_validator(mode="after")
    def parts_fit_role(self) -> CanonicalMessage:
        allowed = ALLOWED_PARTS[self.role]
        offending = sorted({part.type for part in self.content} - allowed)
        if offending:
            msg = f"{self.role} message cannot carry {', '.join(offending)}"
            raise ValueError(msg)
        return self


UserPart = Annotated[TextPart | ImagePart | DocumentPart | ToolResultPart, Field(discriminator="type")]


class SystemMessage(CanonicalMessage):
    role: Literal["system"] = "system"
    content: Annotated[list[TextPart], BeforeValidator(_text_shorthand, json_schema_input_type=list[TextPart] | str)]


class UserMessage(CanonicalMessage):
    role: Literal["user"] = "user"
    content: Annotated[list[UserPart], BeforeValidator(_text_shorthand, json_schema_input_type=list[UserPart] | str)]


class AssistantMessage(CanonicalMessage):
    role: Literal["assistant"] = "assistant"
    content: Annotated[list[AssistantPart], BeforeValidator(_text_shorthand, json_schema_input_type=list[AssistantPart] | str)]


CanonicalMessageValue = Annotated[SystemMessage | UserMessage | AssistantMessage, Field(discriminator="role")]


def _message_models(messages: object) -> object:
    if isinstance(messages, list):
        return [message.model_dump() if isinstance(message, CanonicalMessage) else message for message in messages]
    return messages


class ToolDef(BaseModel):
    """A tool the model may call. Flat: the nesting a surface wraps this in is that surface's business."""

    model_config = WIRE

    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)  # JSON Schema
    cache: Literal["ephemeral"] | None = None
    strict: bool | None = None


class NamedTool(BaseModel):
    model_config = WIRE

    name: str


ToolChoice = Literal["auto", "none", "required"] | NamedTool


class ResponseFormat(BaseModel):
    """A caller's demand for structured output. A model that cannot honor it is a rejection, never a drop."""

    model_config = WIRE

    type: Literal["text", "json_object", "json_schema"]
    json_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def valid_shape(self) -> ResponseFormat:
        if self.type == "json_schema" and self.json_schema is None:
            msg = "json_schema response format requires json_schema"
            raise ValueError(msg)
        if self.type != "json_schema" and self.json_schema is not None:
            msg = f"{self.type} response format does not accept json_schema"
            raise ValueError(msg)
        return self


class TextResponseFormat(ResponseFormat):
    type: Literal["text"] = "text"
    json_schema: None = None


class JsonObjectResponseFormat(ResponseFormat):
    type: Literal["json_object"] = "json_object"
    json_schema: None = None


class JsonSchemaResponseFormat(ResponseFormat):
    type: Literal["json_schema"] = "json_schema"
    json_schema: dict[str, Any]


ResponseFormatValue = Annotated[TextResponseFormat | JsonObjectResponseFormat | JsonSchemaResponseFormat, Field(discriminator="type")]


def _response_format_model(response_format: object) -> object:
    return response_format.model_dump() if isinstance(response_format, ResponseFormat) else response_format


class ReasoningConfig(BaseModel):
    model_config = WIRE

    type: str | None = None
    effort: str | None = None
    summary: str | None = None
    budget_tokens: int | None = Field(default=None, ge=1)
    display: str | None = None


class CanonicalRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    model: str
    messages: Annotated[list[CanonicalMessageValue], BeforeValidator(_message_models)] = Field(min_length=1)
    stream: bool = False
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, gt=0, le=1)
    stop: list[str] | None = None
    seed: int | None = None
    tools: list[ToolDef] | None = None
    tool_choice: ToolChoice | None = None
    response_format: Annotated[ResponseFormatValue | None, BeforeValidator(_response_format_model)] = None
    reasoning: ReasoningConfig | None = None
    parallel_tool_calls: bool | None = None

    @property
    def extra(self) -> dict[str, Any]:
        """The fields the definition does not model, exactly as the caller sent them."""
        return dict(self.__pydantic_extra__ or {})


FinishReason = Literal["stop", "length", "tool_calls", "content_filter"]


class Adjustment(BaseModel):
    """One reconciliation the gateway made to a request, reported on the response rather than silent."""

    model_config = WIRE

    param: str
    action: Literal["clamped", "emulated", "dropped"]
    detail: str


class GatewayInfo(BaseModel):
    """What the gateway did on the way to the provider: the one namespaced place data plane
    internals surface to the caller, so the core response stays about the completion. Grows
    additively as the router grows."""

    model_config = WIRE

    finish_reason: FinishReason | None = None
    adjustments: list[Adjustment] = Field(default_factory=list)


class Usage(BaseModel):
    model_config = WIRE

    input_tokens: int = 0  # total prompt tokens, cache traffic included
    output_tokens: int = 0
    cache_read_tokens: int = 0  # part of input_tokens
    cache_write_tokens: int = 0  # part of input_tokens
    estimated: bool = False


class CanonicalResponse(BaseModel):
    model_config = WIRE

    id: str
    model: str
    content: list[AssistantPart]
    finish_reason: FinishReason | None
    usage: Usage
    gateway: GatewayInfo = Field(default_factory=GatewayInfo)


class TextDelta(BaseModel):
    model_config = WIRE

    type: Literal["text"] = "text"
    text: str


class ReasoningDelta(BaseModel):
    """The provider item id opens replayable reasoning, text follows, and the signature may arrive on a later fragment."""

    model_config = WIRE

    type: Literal["reasoning"] = "reasoning"
    id: str | None = None
    text: str = ""
    signature: str | None = None


class ToolCallDelta(BaseModel):
    """One fragment of a tool call. index ties fragments of parallel calls together: id and name
    arrive on the first fragment, arguments accrete as JSON text across the rest."""

    model_config = WIRE

    type: Literal["tool_call"] = "tool_call"
    index: int = Field(ge=0)
    id: str | None = None
    name: str | None = None
    arguments: str = ""


Delta = Annotated[TextDelta | ReasoningDelta | ToolCallDelta, Field(discriminator="type")]


class CanonicalChunk(BaseModel):
    """One streamed increment. The closing chunk carries finish_reason, usage and gateway, and no delta."""

    model_config = WIRE

    id: str
    delta: Delta | None = None
    finish_reason: FinishReason | None = None
    usage: Usage | None = None
    gateway: GatewayInfo | None = None

    @model_validator(mode="after")
    def valid_shape(self) -> CanonicalChunk:
        if self.delta is not None and any(value is not None for value in (self.finish_reason, self.usage, self.gateway)):
            msg = "a delta chunk cannot carry final accounting"
            raise ValueError(msg)
        if self.delta is None and self.usage is None:
            msg = "a final chunk requires usage"
            raise ValueError(msg)
        return self


class DeltaChunk(CanonicalChunk):
    delta: Delta
    finish_reason: None = None
    usage: None = None
    gateway: None = None


class FinalChunk(CanonicalChunk):
    delta: None = None
    finish_reason: FinishReason | None = None
    usage: Usage
    gateway: GatewayInfo | None = None


CanonicalStreamChunk = DeltaChunk | FinalChunk


def json_schemas() -> dict[str, dict[str, Any]]:
    """The three published faces of the definition, keyed the way taxonomy/schemas/completion names them."""
    return {
        "request": CanonicalRequest.model_json_schema(),
        "response": CanonicalResponse.model_json_schema(),
        "stream": TypeAdapter(CanonicalStreamChunk).json_schema(),
    }
