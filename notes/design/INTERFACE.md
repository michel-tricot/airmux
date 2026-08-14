# The consumer interface, v1

What a caller of the data plane can rely on. This is the locked surface: everything here changes
only additively, and anything not here is not promised. The normative request, response and
stream shapes are the committed schemas in taxonomy/schemas/completion/airllm.*.yaml; this
document is the contract around them.

## Routes

| route | status |
|---|---|
| POST /v1/chat/completions | locked, the native completion route, canonical shape, with OpenAI interpretation (see below) |
| GET /healthz | locked, liveness, always 200 |
| GET /readyz | locked, 200 with a served bundle, 503 without |
| POST /v1/messages | locked, the Anthropic-shaped surface, routed to any provider |

The native route deliberately sits at the path OpenAI clients already have configured. It
speaks the canonical shape, not OpenAI's: a caller who swaps only the base URL keeps working
for plain text conversations (see the shorthand and the open top level below), while typed
payloads (tools, images, tool results) use the canonical forms. If full unmodified-SDK
compatibility lands later, it lands on this same route as shape-detected interpretation,
additively; it never gets a route of its own.

## Authentication

`Authorization: Bearer sk-inf-...`, an inference key minted by the control plane. Missing or
unknown tokens are 401. Keys are org- and workspace-scoped; revocation is absence from the next
bundle, effective within one poll interval.

## The request

`airllm.request.yaml`. The core fields: model, messages, stream, max_tokens, temperature,
top_p, stop, seed, tools, tool_choice, response_format.

- Messages are role plus a list of typed content parts (text, image, reasoning, tool_call,
  tool_result). A tool result is a user part, not a role
- Shorthand: a message's content may be a plain string, normalized to a single text part at the
  edge. The typed form is the only thing stored, translated or emitted
- The top level is open: fields the core does not model are captured and forwarded upstream
  when the provider accepts them, never a 400. What cannot be forwarded is dropped and reported
  (see gateway.adjustments). Nested shapes are closed: an unknown field inside a message, part
  or tool is a 400
- Rejection beats silence for meaning-bearing demands: a response_format the target model
  cannot honor is a 4xx, not a drop

## The response

`airllm.response.yaml`: id, model, content (assistant parts only), finish_reason (stop, length,
tool_calls, content_filter), usage, gateway.

- usage: input_tokens (cache traffic included), output_tokens, cache_read_tokens,
  cache_write_tokens, estimated
- gateway is the one namespaced envelope where data plane internals surface to the caller; the
  rest of the response stays about the completion. Its first member is adjustments, the audit
  trail of the gateway's reconciliations: one entry per request field clamped, emulated or
  dropped on the way upstream, `{param, action, detail}`. An empty list means the request went
  through as sent. Routing facts (attempts, timing and the like) will join it additively
- The response is route-invariant: nothing provider-specific ever appears at the top level, and
  a caller cannot tell from the shape which deployment served them
- Null-valued fields are omitted on the wire; absent and null read the same
- Callers must ignore response fields they do not recognize; additions are not breaking

## Streaming

`stream: true` returns `text/event-stream`. Every frame is `data: <JSON>\n\n`.

- Each data frame is one chunk per `airllm.stream.yaml`: id plus a typed delta (text,
  reasoning, or a tool_call fragment carrying index, with id and name on the first fragment and
  arguments accreting as JSON text)
- The closing chunk carries finish_reason, usage and gateway, and no delta
- The stream ends with `data: [DONE]`
- An error after streaming has begun is delivered as a `data: {"error": {"code", "message"}}`
  frame followed by `data: [DONE]`; the HTTP status is already spent by then

## OpenAI interpretation on the native route

An unmodified OpenAI client that swapped only its base URL is recognized and answered in the
shape it spoke. This is additive: detection can never change what a canonical caller sees.

Recognition, in order:

1. An explicit `x-airllm-dialect: openai` or `x-airllm-dialect: canonical` header wins
2. The client fingerprint: a `User-Agent` starting with `OpenAI/`, which the official SDKs send
   on every request. Deliberately not the `x-stainless-*` headers: those mean "a
   Stainless-generated SDK", which other vendors' clients also are
3. Unambiguous body shapes: a `tool` or `developer` role, `tool_calls` on a message, a nested
   `function` wrapper in tools or tool_choice, an `image_url` content block, or
   `max_completion_tokens`

A text-only body with none of those parses as canonical: the two dialects are shape-identical
there, which is exactly what the fingerprint and the override exist for.

An interpreted request is answered as OpenAI's shapes, buffered (`chat.completion`, choices
axis) and streamed (`chat.completion.chunk` objects, a usage-bearing final chunk with no
choices, `data: [DONE]`). The gateway envelope rides along as an additional field on the
completion and on the usage-bearing chunk; SDKs ignore fields they do not know. Fields the
interpretation does not consume follow the same open-top-level rules as canonical extras:
captured, forwarded when the provider profile allows, reported under gateway.adjustments when not.

## The Messages surface

POST /v1/messages speaks Anthropic's Messages dialect, buffered and streamed, routed through
the same canonical middle to any provider. The route binds the dialect: every answer, errors
included, uses Anthropic's shapes (`{"type": "error", "error": {...}}`, named SSE events).
Auth is the same bearer key; Claude Code's ANTHROPIC_AUTH_TOKEN works as is. Thinking
signatures round-trip. Fields the dialect does not consume follow the extras rules above, so
thinking and top_k reach providers whose profile accepts them. The gateway envelope rides as
an extra field on the buffered message and on the usage-bearing message_delta.

## Errors

Before any bytes stream, errors are plain HTTP: `{"error": {"code": "...", "message": "..."}}`.

| status | code | meaning |
|---|---|---|
| 400 | invalid_request | body does not validate against the request schema |
| 401 | missing_bearer_token, invalid_token | no key, or a key the bundle does not know |
| 402 | credential_unavailable | no provider credential at any tier for this caller |
| 404 | unknown_model | the model is not in the caller's catalog |
| 502 | upstream_error, upstream_unreachable, credential_missing | the provider failed or the named credential has no value |
| 503 | bundle_unavailable, credential_backend_unavailable | the gateway cannot serve yet |
| 504 | upstream_timeout | the provider did not answer in time |

Codes are additive; callers should branch on status class first, code second.

## What locked means

- Existing fields never change type or meaning; new fields may appear anywhere
- New content part types, delta types, finish reasons, adjustment actions, gateway members and
  error codes may appear; consumers treat unknown enum members as unknown, not as errors
- The shorthand and the open top level are contract, not courtesy: they will not be revoked
- Schema changes land as diffs to taxonomy/schemas/completion/airllm.*.yaml, which CI keeps in
  lockstep with the code
