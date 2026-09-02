from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from data_plane.canonical import (
    AssistantMessage,
    AssistantPart,
    CanonicalMessageValue,
    CanonicalRequest,
    DocumentPart,
    ImagePart,
    JsonObjectResponseFormat,
    JsonSchemaResponseFormat,
    NamedTool,
    ReasoningPart,
    ResponseFormatValue,
    SystemMessage,
    TextPart,
    ToolCallPart,
    ToolChoice,
    ToolDef,
    ToolResultPart,
    UserMessage,
    UserPart,
)

# The conversations every surface must parse into the definition and every adapter must render out of it.


class Case(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    messages: list[CanonicalMessageValue]
    tools: list[ToolDef] = Field(default_factory=list)
    tool_choice: ToolChoice | None = None
    stop: list[str] | None = None
    response_format: ResponseFormatValue | None = None


def request_of(case: Case, **overrides) -> CanonicalRequest:
    request = CanonicalRequest(
        model="gpt-test",
        messages=case.messages,
        tools=case.tools or None,
        tool_choice=case.tool_choice,
        stop=case.stop,
        response_format=case.response_format,
    )
    return request.model_copy(update=overrides) if overrides else request


WEATHER = ToolDef(
    name="get_weather",
    description="Get the weather for a city",
    parameters={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
)

SEARCH = ToolDef(
    name="search",
    description="Search the web",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
)


def user(*parts: UserPart) -> UserMessage:
    return UserMessage(content=list(parts))


def assistant(*parts: AssistantPart) -> AssistantMessage:
    return AssistantMessage(content=list(parts))


def system(text: str) -> SystemMessage:
    return SystemMessage(content=[TextPart(text=text)])


CORPUS: list[Case] = [
    Case(
        name="single_turn_text",
        messages=[user(TextPart(text="hi"))],
    ),
    Case(
        name="multi_turn_text",
        messages=[
            user(TextPart(text="What is the capital of France?")),
            assistant(TextPart(text="Paris")),
            user(TextPart(text="And of Spain?")),
        ],
    ),
    Case(
        name="system_prompt",
        messages=[
            system("You are terse. Answer in one word."),
            user(TextPart(text="What is the capital of France?")),
        ],
    ),
    Case(
        name="image_by_url",
        messages=[user(TextPart(text="What is in this image?"), ImagePart(media_type="image/png", url="https://example.com/cat.png"))],
    ),
    Case(
        name="image_by_value",
        messages=[user(TextPart(text="What is in this image?"), ImagePart(media_type="image/png", data="iVBORw0KGgo="))],
    ),
    Case(
        name="document_by_value",
        messages=[
            user(TextPart(text="What is in this document?"), DocumentPart(filename="audit.pdf", media_type="application/pdf", data="JVBERi0="))
        ],
    ),
    Case(
        name="tool_declared_and_called",
        messages=[
            user(TextPart(text="What is the weather in Paris?")),
            assistant(ToolCallPart(id="call_1", name="get_weather", arguments='{"city":"Paris"}')),
        ],
        tools=[WEATHER],
    ),
    Case(
        name="tool_result_round_trip",
        messages=[
            user(TextPart(text="What is the weather in Paris?")),
            assistant(ToolCallPart(id="call_1", name="get_weather", arguments='{"city":"Paris"}')),
            user(ToolResultPart(call_id="call_1", content=[TextPart(text="18C, light rain")])),
        ],
        tools=[WEATHER],
    ),
    Case(
        name="tool_result_is_error",
        messages=[
            user(TextPart(text="What is the weather in Atlantis?")),
            assistant(ToolCallPart(id="call_1", name="get_weather", arguments='{"city":"Atlantis"}')),
            user(ToolResultPart(call_id="call_1", content=[TextPart(text="unknown city")], is_error=True)),
        ],
        tools=[WEATHER],
    ),
    Case(
        name="parallel_tool_calls",
        messages=[
            user(TextPart(text="Weather in Paris, and search for umbrellas")),
            assistant(
                ToolCallPart(id="call_1", name="get_weather", arguments='{"city":"Paris"}'),
                ToolCallPart(id="call_2", name="search", arguments='{"query":"umbrellas"}'),
            ),
            user(
                ToolResultPart(call_id="call_1", content=[TextPart(text="18C, light rain")]),
                ToolResultPart(call_id="call_2", content=[TextPart(text="Umbrella shops near you")]),
            ),
        ],
        tools=[WEATHER, SEARCH],
    ),
    Case(
        name="tool_choice_required",
        messages=[user(TextPart(text="Paris"))],
        tools=[WEATHER, SEARCH],
        tool_choice="required",
    ),
    Case(
        name="tool_choice_named",
        messages=[user(TextPart(text="Paris"))],
        tools=[WEATHER, SEARCH],
        tool_choice=NamedTool(name="get_weather"),
    ),
    Case(
        name="reasoning_carried_into_next_turn",
        messages=[
            user(TextPart(text="A bat and a ball cost $1.10. The bat costs $1.00 more. How much is the ball?")),
            assistant(
                ReasoningPart(id="rs_abc123", text="Let x be the ball. x + (x + 1) = 1.10, so x = 0.05", signature="sig_abc123"),
                TextPart(text="$0.05"),
            ),
            user(TextPart(text="Show the algebra again")),
        ],
    ),
    Case(
        name="reasoning_then_tool_call",
        messages=[
            user(TextPart(text="What is the weather in Paris?")),
            assistant(
                ReasoningPart(id="rs_def456", text="The user wants current weather; call the tool", signature="sig_def456"),
                ToolCallPart(id="call_1", name="get_weather", arguments='{"city":"Paris"}'),
            ),
        ],
        tools=[WEATHER],
    ),
    Case(
        name="cache_breakpoint_after_system",
        messages=[
            SystemMessage(content=[TextPart(text="A very long system prompt worth caching.", cache="ephemeral")]),
            user(TextPart(text="hi")),
        ],
    ),
    Case(
        name="stop_sequence",
        messages=[user(TextPart(text="Count to ten"))],
        stop=["5"],
    ),
    Case(
        name="json_response_format",
        messages=[user(TextPart(text="Give me a city and its country"))],
        response_format=JsonObjectResponseFormat(),
    ),
    Case(
        name="json_schema_response_format",
        messages=[user(TextPart(text="Give me a city and its country"))],
        response_format=JsonSchemaResponseFormat(
            # the vendor shape: a named wrapper around the schema, not the schema itself
            json_schema={
                "name": "city_and_country",
                "schema": {"type": "object", "properties": {"city": {"type": "string"}, "country": {"type": "string"}}},
            },
        ),
    ),
]
