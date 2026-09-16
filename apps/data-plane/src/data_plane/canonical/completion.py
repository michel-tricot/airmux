"""The completion definition the gateway owns.

Requests arrive in this shape, responses and stream chunks leave in it; adapters translate
outward to whatever the upstream provider speaks. The three faces (request, response, stream)
are published as JSON Schema into taxonomy/schemas/completion via `airmux gateway schema`, where they
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

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

_WIRE = ConfigDict(frozen=True, extra="forbid")


class CanonicalPart(BaseModel):
    """One piece of a message. cache marks a prompt-cache breakpoint after this part, honored by
    providers that take explicit breakpoints and ignored by providers that cache on their own."""

    model_config = _WIRE

    cache: Literal["ephemeral"] | None = None


class CanonicalTextPart(CanonicalPart):
    type: Literal["text"] = "text"
    text: str


class CanonicalImagePart(CanonicalPart):
    """An image by reference or by value; exactly one of url or data is set."""

    type: Literal["image"] = "image"
    url: str | None = None
    data: str | None = None  # base64, no data: prefix
    media_type: str | None = None  # required alongside data, absent for a url the provider fetches itself

    @model_validator(mode="after")
    def one_source(self) -> CanonicalImagePart:
        if (self.url is None) == (self.data is None):
            msg = "image part needs exactly one of url or data"
            raise ValueError(msg)
        if self.data is not None and not self.media_type:
            msg = "inline image data needs a media_type"
            raise ValueError(msg)
        return self


class CanonicalDocumentPart(CanonicalPart):
    type: Literal["document"] = "document"
    filename: str | None = None
    url: str | None = None
    data: str | None = None
    file_id: str | None = None
    media_type: str | None = None

    @model_validator(mode="after")
    def one_source(self) -> CanonicalDocumentPart:
        if sum(source is not None for source in (self.url, self.data, self.file_id)) != 1:
            msg = "document part needs exactly one of url, data or file_id"
            raise ValueError(msg)
        if self.data is not None and not self.media_type:
            msg = "inline document data needs a media_type"
            raise ValueError(msg)
        return self


class CanonicalReasoningPart(CanonicalPart):
    """Model reasoning. signature is an opaque provider token: a provider that issues one rejects a
    later turn whose reasoning comes back without it."""

    type: Literal["reasoning"] = "reasoning"
    id: str | None = None
    text: str
    signature: str | None = None


class CanonicalToolCallPart(CanonicalPart):
    """A tool invocation. arguments stays JSON text: parsing it loses a truncated stream's partial
    arguments and re-serializing changes the key order the provider chose."""

    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: str


CanonicalToolResultContent = Annotated[CanonicalTextPart | CanonicalImagePart, Field(discriminator="type")]


def _text_shorthand(content: object) -> object:
    """A plain string is shorthand for a single text part; the typed form is the only one stored or emitted."""
    return [{"type": "text", "text": content}] if isinstance(content, str) else content


class CanonicalToolResultPart(CanonicalPart):
    """The outcome of a tool call, carried as a user part rather than as its own role."""

    type: Literal["tool_result"] = "tool_result"
    call_id: str
    content: Annotated[
        list[CanonicalToolResultContent],
        BeforeValidator(_text_shorthand, json_schema_input_type=list[CanonicalToolResultContent] | str),
    ]
    is_error: bool = False


CanonicalContentPart = Annotated[
    CanonicalTextPart | CanonicalImagePart | CanonicalDocumentPart | CanonicalReasoningPart | CanonicalToolCallPart | CanonicalToolResultPart,
    Field(discriminator="type"),
]

CanonicalAssistantPart = Annotated[CanonicalTextPart | CanonicalReasoningPart | CanonicalToolCallPart, Field(discriminator="type")]


class _CanonicalMessage(BaseModel):
    model_config = _WIRE


CanonicalUserPart = Annotated[
    CanonicalTextPart | CanonicalImagePart | CanonicalDocumentPart | CanonicalToolResultPart,
    Field(discriminator="type"),
]


class CanonicalSystemMessage(_CanonicalMessage):
    role: Literal["system"] = "system"
    content: Annotated[
        list[CanonicalTextPart],
        BeforeValidator(_text_shorthand, json_schema_input_type=list[CanonicalTextPart] | str),
    ]


class CanonicalUserMessage(_CanonicalMessage):
    role: Literal["user"] = "user"
    content: Annotated[
        list[CanonicalUserPart],
        BeforeValidator(_text_shorthand, json_schema_input_type=list[CanonicalUserPart] | str),
    ]


class CanonicalAssistantMessage(_CanonicalMessage):
    role: Literal["assistant"] = "assistant"
    content: Annotated[
        list[CanonicalAssistantPart],
        BeforeValidator(_text_shorthand, json_schema_input_type=list[CanonicalAssistantPart] | str),
    ]


CanonicalMessage = Annotated[CanonicalSystemMessage | CanonicalUserMessage | CanonicalAssistantMessage, Field(discriminator="role")]


class CanonicalToolDef(BaseModel):
    """A tool the model may call. Flat: the nesting a surface wraps this in is that surface's business."""

    model_config = _WIRE

    name: str
    description: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)  # JSON Schema
    cache: Literal["ephemeral"] | None = None
    strict: bool | None = None


class CanonicalNamedTool(BaseModel):
    model_config = _WIRE

    name: str


CanonicalToolChoice = Literal["auto", "none", "required"] | CanonicalNamedTool


class _ResponseFormat(BaseModel):
    """A caller's demand for structured output. A model that cannot honor it is a rejection, never a drop."""

    model_config = _WIRE


class CanonicalTextResponseFormat(_ResponseFormat):
    type: Literal["text"] = "text"
    json_schema: None = None


class CanonicalJsonObjectResponseFormat(_ResponseFormat):
    type: Literal["json_object"] = "json_object"
    json_schema: None = None


class CanonicalJsonSchemaResponseFormat(_ResponseFormat):
    type: Literal["json_schema"] = "json_schema"
    json_schema: dict[str, Any]


CanonicalResponseFormat = Annotated[
    CanonicalTextResponseFormat | CanonicalJsonObjectResponseFormat | CanonicalJsonSchemaResponseFormat,
    Field(discriminator="type"),
]


class CanonicalReasoningConfig(BaseModel):
    model_config = _WIRE

    type: str | None = None
    effort: str | None = None
    summary: str | None = None
    budget_tokens: int | None = Field(default=None, ge=1)
    display: str | None = None


class CanonicalRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")

    model: str
    messages: list[CanonicalMessage] = Field(min_length=1)
    stream: bool = Field(default=False, strict=True)
    max_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, gt=0, le=1)
    stop: list[str] | None = None
    seed: int | None = None
    tools: list[CanonicalToolDef] | None = None
    tool_choice: CanonicalToolChoice | None = None
    response_format: CanonicalResponseFormat | None = None
    reasoning: CanonicalReasoningConfig | None = None
    parallel_tool_calls: bool | None = Field(default=None, strict=True)

    @property
    def extra(self) -> dict[str, Any]:
        """The fields the definition does not model, exactly as the caller sent them."""
        return dict(self.__pydantic_extra__ or {})


CanonicalFinishReason = Literal["stop", "length", "tool_calls", "content_filter"]


class CanonicalAdjustment(BaseModel):
    """One reconciliation the gateway made to a request, reported on the response rather than silent."""

    model_config = _WIRE

    param: str
    action: Literal["clamped", "emulated", "dropped"]
    detail: str


class CanonicalGatewayInfo(BaseModel):
    """What the gateway did on the way to the provider: the one namespaced place data plane
    internals surface to the caller, so the core response stays about the completion. Grows
    additively as the router grows."""

    model_config = _WIRE

    finish_reason: CanonicalFinishReason | None = None
    adjustments: list[CanonicalAdjustment] = Field(default_factory=list)


class CanonicalUsage(BaseModel):
    model_config = _WIRE

    input_tokens: int = 0  # total prompt tokens, cache traffic included
    output_tokens: int = 0
    cache_read_tokens: int = 0  # part of input_tokens
    cache_write_tokens: int = 0  # part of input_tokens
    estimated: bool = False


class CanonicalResponse(BaseModel):
    model_config = _WIRE

    id: str
    model: str
    content: list[CanonicalAssistantPart]
    finish_reason: CanonicalFinishReason | None
    usage: CanonicalUsage
    gateway: CanonicalGatewayInfo = Field(default_factory=CanonicalGatewayInfo)


class CanonicalTextDelta(BaseModel):
    model_config = _WIRE

    type: Literal["text"] = "text"
    text: str


class CanonicalReasoningDelta(BaseModel):
    """The provider item id opens replayable reasoning, text follows, and the signature may arrive on a later fragment."""

    model_config = _WIRE

    type: Literal["reasoning"] = "reasoning"
    id: str | None = None
    text: str = ""
    signature: str | None = None


class CanonicalToolCallDelta(BaseModel):
    """One fragment of a tool call. index ties fragments of parallel calls together: id and name
    arrive on the first fragment, arguments accrete as JSON text across the rest."""

    model_config = _WIRE

    type: Literal["tool_call"] = "tool_call"
    index: int = Field(ge=0)
    id: str | None = None
    name: str | None = None
    arguments: str = ""


CanonicalDelta = Annotated[CanonicalTextDelta | CanonicalReasoningDelta | CanonicalToolCallDelta, Field(discriminator="type")]


class CanonicalChunk(BaseModel):
    """One streamed increment. The closing chunk carries finish_reason, usage and gateway, and no delta."""

    model_config = _WIRE

    id: str
    delta: CanonicalDelta | None = None
    finish_reason: CanonicalFinishReason | None = None
    usage: CanonicalUsage | None = None
    gateway: CanonicalGatewayInfo | None = None


def json_schemas() -> dict[str, dict[str, Any]]:
    """The three published faces of the definition, keyed the way taxonomy/schemas/completion names them."""
    return {
        "request": CanonicalRequest.model_json_schema(),
        "response": CanonicalResponse.model_json_schema(),
        "stream": CanonicalChunk.model_json_schema(),
    }
