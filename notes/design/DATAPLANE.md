# Data plane rebuild: an owned-schema proxy

The data plane is a model router. Today it routes nothing: it translates two client surfaces into two
provider dialects through a request path that grew past reviewability. This plan rebuilds the request
path from scratch around one completion schema we own, while keeping the two subsystems that already
work: bundle distribution and event tracking.

## What survives, what dies

Survives untouched:

- lib/contract: bundle, events, signing, secrets
- The bundle path: poller, holder, cache, auth
- The event path: outbox backends, control plane ingest
- heartbeat, config, transport, tasks, credentials

Dies: the request path, on main and on canonical-content-types both. The branch is never merged; it is
a quarry. Pieces are copied out one at a time, each copy reviewed as it lands, and the branch is
deleted once steps 2 through 5 have harvested it.

Reversed decision: the branch retired the canonical route and served OpenAI's shape on OpenAI's route.
The rebuild is built on the opposite: one ingress schema we own, compat dialects optional and last.

## Steps

Each step is one PR with a stated proof. Proof is a real request against a running data plane, not
pytest output.

### 1. Strip to the keeper skeleton

Mostly deletions. Delete ingress, adapters, canonical types, normalize, policy, and metering; the last
three return with the request path, and metering's Usage type belongs to the step 2 definition. app.py
shrinks to lifespan, /readyz and /healthz. Tests trim to what the keepers exercise.

**Proof:** both planes running, bundle polled and admitted, heartbeat visible, one synthetic usage
event shipped and ingested (ingested=1 on first send, 0 on replay).

### 2. Own the completion definition

No HTTP. One module: fully typed request, response, and stream delta. Content part union (text, image,
reasoning, tool call, tool result), CanonicalMessage with role-to-part validation, ToolDef, ToolChoice,
ResponseFormat, Usage. No dict[str, Any] anywhere, chunks included: the branch typed requests but left
the streaming seam untyped, and that hole is where the mess leaked back in.

Harvest the branch's content.py design here, by copy with review.

The request is open at the top level: swapping a provider's base URL for the gateway must keep
working, so fields the core does not model are captured for forwarding rather than rejected.
Nested shapes stay closed. The response and the closing chunk carry adjustments, the audit
trail of every field the gateway dropped or changed on the way upstream.

The schema is exported as YAML into taxonomy/schemas/completion/ as airllm.request, airllm.response
and airllm.stream: the definition we own, sitting as a column beside the providers it routes to.

Corpus: roughly ten canonical conversations as typed constructors (text, multi-turn tools, reasoning,
images). Every later step reuses this fixture.

**Proof:** round-trip tests over the corpus; the schema YAML diff is the review artifact.

### 3. Proxy path, one adapter, buffered only

The adapter interface (construction-injected credential, transform_request, transform_response,
map_error) and the openai_compatible adapter. One native route: auth, evaluate(), credential resolve,
transform, upstream call, canonical response, one metering point. policy and metering return here.
The handler lives in its own module; app.py stays routes and lifespan.

**Proof:** a real request through the running data plane to a real provider; the usage event with a
real cost breakdown lands in the control plane.

### 4. Streaming and cancellation accounting

new_stream_state, frame, transform_stream_event, finalize for openai_compatible; SSE egress in our own
stream shape. Streaming tests are a pure fold over recorded byte logs with adversarial chunk splits,
and finalize must be valid at every prefix.

**Proof:** a real streamed request; disconnect mid-stream and show the cancelled event carrying
partial usage.

### 5. Second adapter: anthropic

Proves the interface generalizes. Harvest the branch's wire conversion logic, split so no 457-line
module returns. Adopt the branch's conformance idea wholesale: tests parameterized over the registry,
rendered upstream bytes validated against the vendor schemas in taxonomy/schemas/completion/, with
KNOWN_REJECTIONS pinning real incompatibilities.

**Proof:** the same corpus of real requests against Anthropic, streamed and buffered.

### 6. Adjustments as data, not branches

Provider profile in the bundle: auth scheme, endpoint path, field aliases, accepted fields, open or
closed schema, derived from taxonomy. Request extras pass through with profile aliasing; anything
dropped or clamped lands in the response's adjustments and on the usage event. Profile fields are declarative
facts, never predicates; a provider that needs a predicate needs an adapter.

**Proof:** a field absent from the typed core, such as seed or top_k, reaches a provider that accepts
it; onboarding a quirky OpenAI-compatible provider is a config change with zero code.

### 7. Later, explicitly out of scope

- Compat dialects (/v1/chat/completions, /v1/messages) as pure translators onto the native schema, if
  drop-in client support is wanted
- Routing proper: deployments, the unserviceable() filter, ranked candidates, failover. The sequencing
  in the canonical-content-types branch's ROUTER.md (steps 3 through 9) remains right from there

## Guardrails

- One step, one PR, one concern. Renames land alone
- Diff cap per PR around 500 lines; a step that wants more splits
- The schema YAML exports and the typed corpus are the review currency: any behavior change must show
  up as a diff in one of them
- app.py never exceeds about 150 lines; the moment it grows a second concern, that concern gets a
  module
- Never merge canonical-content-types; delete it once harvested
