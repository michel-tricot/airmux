from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from data_plane.canonical import (
    CanonicalAssistantMessage,
    CanonicalAssistantPart,
    CanonicalDocumentPart,
    CanonicalImagePart,
    CanonicalJsonObjectResponseFormat,
    CanonicalJsonSchemaResponseFormat,
    CanonicalMessage,
    CanonicalNamedTool,
    CanonicalReasoningPart,
    CanonicalRequest,
    CanonicalResponseFormat,
    CanonicalSystemMessage,
    CanonicalTextPart,
    CanonicalToolCallPart,
    CanonicalToolChoice,
    CanonicalToolDef,
    CanonicalToolResultPart,
    CanonicalUserMessage,
    CanonicalUserPart,
)

# The conversations every surface must parse into the definition and every adapter must render out of it.


class Case(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    messages: list[CanonicalMessage]
    tools: list[CanonicalToolDef] = Field(default_factory=list)
    tool_choice: CanonicalToolChoice | None = None
    stop: list[str] | None = None
    response_format: CanonicalResponseFormat | None = None


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


WEATHER = CanonicalToolDef(
    name="get_weather",
    description="Get the weather for a city",
    parameters={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
)

SEARCH = CanonicalToolDef(
    name="search",
    description="Search the web",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
)


def user(*parts: CanonicalUserPart) -> CanonicalUserMessage:
    return CanonicalUserMessage(content=list(parts))


def assistant(*parts: CanonicalAssistantPart) -> CanonicalAssistantMessage:
    return CanonicalAssistantMessage(content=list(parts))


def system(text: str) -> CanonicalSystemMessage:
    return CanonicalSystemMessage(content=[CanonicalTextPart(text=text)])


CORPUS: list[Case] = [
    Case(
        name="single_turn_text",
        messages=[user(CanonicalTextPart(text="hi"))],
    ),
    Case(
        name="multi_turn_text",
        messages=[
            user(CanonicalTextPart(text="What is the capital of France?")),
            assistant(CanonicalTextPart(text="Paris")),
            user(CanonicalTextPart(text="And of Spain?")),
        ],
    ),
    Case(
        name="system_prompt",
        messages=[
            system("You are terse. Answer in one word."),
            user(CanonicalTextPart(text="What is the capital of France?")),
        ],
    ),
    Case(
        name="image_by_url",
        messages=[
            user(CanonicalTextPart(text="What is in this image?"), CanonicalImagePart(media_type="image/png", url="https://example.com/cat.png"))
        ],
    ),
    Case(
        name="image_by_value",
        messages=[user(CanonicalTextPart(text="What is in this image?"), CanonicalImagePart(media_type="image/png", data="iVBORw0KGgo="))],
    ),
    Case(
        name="document_by_value",
        messages=[
            user(
                CanonicalTextPart(text="What is in this document?"),
                CanonicalDocumentPart(filename="audit.pdf", media_type="application/pdf", data="JVBERi0="),
            )
        ],
    ),
    Case(
        name="tool_declared_and_called",
        messages=[
            user(CanonicalTextPart(text="What is the weather in Paris?")),
            assistant(CanonicalToolCallPart(id="call_1", name="get_weather", arguments='{"city":"Paris"}')),
        ],
        tools=[WEATHER],
    ),
    Case(
        name="tool_result_round_trip",
        messages=[
            user(CanonicalTextPart(text="What is the weather in Paris?")),
            assistant(CanonicalToolCallPart(id="call_1", name="get_weather", arguments='{"city":"Paris"}')),
            user(CanonicalToolResultPart(call_id="call_1", content=[CanonicalTextPart(text="18C, light rain")])),
        ],
        tools=[WEATHER],
    ),
    Case(
        name="tool_result_is_error",
        messages=[
            user(CanonicalTextPart(text="What is the weather in Atlantis?")),
            assistant(CanonicalToolCallPart(id="call_1", name="get_weather", arguments='{"city":"Atlantis"}')),
            user(CanonicalToolResultPart(call_id="call_1", content=[CanonicalTextPart(text="unknown city")], is_error=True)),
        ],
        tools=[WEATHER],
    ),
    Case(
        name="parallel_tool_calls",
        messages=[
            user(CanonicalTextPart(text="Weather in Paris, and search for umbrellas")),
            assistant(
                CanonicalToolCallPart(id="call_1", name="get_weather", arguments='{"city":"Paris"}'),
                CanonicalToolCallPart(id="call_2", name="search", arguments='{"query":"umbrellas"}'),
            ),
            user(
                CanonicalToolResultPart(call_id="call_1", content=[CanonicalTextPart(text="18C, light rain")]),
                CanonicalToolResultPart(call_id="call_2", content=[CanonicalTextPart(text="Umbrella shops near you")]),
            ),
        ],
        tools=[WEATHER, SEARCH],
    ),
    Case(
        name="tool_choice_required",
        messages=[user(CanonicalTextPart(text="Paris"))],
        tools=[WEATHER, SEARCH],
        tool_choice="required",
    ),
    Case(
        name="tool_choice_named",
        messages=[user(CanonicalTextPart(text="Paris"))],
        tools=[WEATHER, SEARCH],
        tool_choice=CanonicalNamedTool(name="get_weather"),
    ),
    Case(
        name="reasoning_carried_into_next_turn",
        messages=[
            user(CanonicalTextPart(text="A bat and a ball cost $1.10. The bat costs $1.00 more. How much is the ball?")),
            assistant(
                CanonicalReasoningPart(id="rs_abc123", text="Let x be the ball. x + (x + 1) = 1.10, so x = 0.05", signature="sig_abc123"),
                CanonicalTextPart(text="$0.05"),
            ),
            user(CanonicalTextPart(text="Show the algebra again")),
        ],
    ),
    Case(
        name="reasoning_then_tool_call",
        messages=[
            user(CanonicalTextPart(text="What is the weather in Paris?")),
            assistant(
                CanonicalReasoningPart(id="rs_def456", text="The user wants current weather; call the tool", signature="sig_def456"),
                CanonicalToolCallPart(id="call_1", name="get_weather", arguments='{"city":"Paris"}'),
            ),
        ],
        tools=[WEATHER],
    ),
    Case(
        name="cache_breakpoint_after_system",
        messages=[
            CanonicalSystemMessage(content=[CanonicalTextPart(text="A very long system prompt worth caching.", cache="ephemeral")]),
            user(CanonicalTextPart(text="hi")),
        ],
    ),
    Case(
        name="stop_sequence",
        messages=[user(CanonicalTextPart(text="Count to ten"))],
        stop=["5"],
    ),
    Case(
        name="json_response_format",
        messages=[user(CanonicalTextPart(text="Give me a city and its country"))],
        response_format=CanonicalJsonObjectResponseFormat(),
    ),
    Case(
        name="json_schema_response_format",
        messages=[user(CanonicalTextPart(text="Give me a city and its country"))],
        response_format=CanonicalJsonSchemaResponseFormat(
            # the vendor shape: a named wrapper around the schema, not the schema itself
            json_schema={
                "name": "city_and_country",
                "schema": {"type": "object", "properties": {"city": {"type": "string"}, "country": {"type": "string"}}},
            },
        ),
    ),
]
