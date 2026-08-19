# Failure modes

Each of these cost a round trip while the catalog was built. Symptom, cause, what to do.

## A 200 is not a success

**Symptom** `curl -o /dev/null -w "%{http_code}"` returns 200 for a spec URL, and the body
is an HTML shell.

**Cause** Next.js and similar frameworks answer every path with the app shell.
`console.upstage.ai/openapi.json`, `api.writer.com/openapi.json` and
`platform.minimax.io/openapi.json` all do this.

**Do** Check the body, never the status. Grep for `"openapi"` or `"swagger"` before
believing a spec exists.

## A spec can exist and be worthless

Three distinct versions, all seen:

- **Empty framework default.** `api.reka.ai/openapi.json` is a FastAPI stub with zero paths
- **Path but no request body.** Novita declares `/chat/completions` and attaches no schema
- **200 with an empty schema.** DeepInfra declares a response of `{}` on both surfaces

**Do** Assert on content: paths exist, the operation has a `requestBody`, the schema has a
root form. An extractor that writes `{"$schema": ...}` and nothing else has found nothing.

## Composition nests, and naive walkers lose whole branches

**Symptom** A provider shows as not supporting `$.messages`.

**Cause** Its request is a `oneOf` of per-model variants, each an `allOf` of a shared base
and an inline delta. Expanding composition one level finds no `properties` and stops.
Moonshot is built this way; it reported 0 fields, then 52 once fixed.

**Do** Flatten `$ref`, `oneOf`, `anyOf` and `allOf` transitively with cycle detection. If a
provider's field count looks impossibly low, this is why.

## The obvious endpoint is the wrong product

**Symptom** A spec parses, has paths, and contains no chat completions.

**Cause** `cloud.lambda.ai/api/v1/openapi.json` is Lambda's GPU instance API. Same vendor,
different product.

**Do** Confirm the spec contains the inference path before recording it.

## Hosts migrate mid-research

Seen in a single week: Vertex AI became Gemini Enterprise Agent Platform, Nebius AI Studio
became Nebius Token Factory with a new API host, `platform.moonshot.ai` became
`platform.kimi.ai`, `docs.anthropic.com` became `platform.claude.com`, Hyperbolic moved
`.xyz` to `.ai`, `platform.openai.com/docs` became `developers.openai.com`.

**Do** Follow redirects and record the resolved URL. When a product is renamed, use the new
name and keep the old id if that is still what the endpoint is called: Vertex is
`gemini-enterprise-agent-platform` in docs and still `aiplatform.googleapis.com` on the
wire.

## Pricing pages print display names

`GLM-5.2` is not a model id; `glm-5.2` is. Kimi's page says "Kimi K3", the API wants
`kimi-k3`. Prefer a spec enum. If there is none, find a code sample rather than a table.

## JS-rendered documentation

OpenAI's models page and Nebius's catalog return a shell to a plain fetch. Summarizers will
confidently return the handful of models in the static payload and miss the rest.

**Do** Treat a suspiciously short list as a failed fetch, not a short catalog.

## Not every model has the fields you are asking for

A context window and a max output token count are undefined for embeddings, rerankers,
image, video and speech models. Roughly a fifth of a provider's catalog is these. Filling
them to satisfy a not-null rule puts invented numbers into routing data.

**Do** Classify first, then require the fields where they mean something. `model_kind.py`
does this at collection.

## Auth header names are not guessable

Cohere's SDK reads `CO_API_KEY`, not `COHERE_API_KEY`. Anthropic uses `x-api-key`, Reka
uses `X-Api-Key`, Gemini uses `x-goog-api-key`, Azure uses `api-key`. DeepSeek uses bearer
on its OpenAI surface and `x-api-key` on its Anthropic one.

**Do** Read `securitySchemes`, or probe with an invalid key.

## An API that returns 200 for an unknown model

SambaNova validates the model before the credential, so a bad key with a bad model returns
`model_not_found` rather than 401. Do not conclude auth succeeded.

## A 2xx is not capability evidence

**Symptom** A model is marked vision, tools or structured-output capable because the
request returned successfully.

**Cause** Providers may ignore unknown fields or answer in ordinary text. Request
acceptance proves parameter acceptance at most; it does not prove the requested behavior.

**Do** Require an observable protocol result: the exact generated image challenge, a named
tool call, two distinct parallel calls, valid constrained JSON, reasoning content, or SSE
framing. A 2xx without the behavior is inconclusive, not unsupported.

## Operational failures are not unsupported features

Authentication, entitlement, throttling, timeouts, transport errors and server failures
say nothing durable about model capability. Keep them in the local probe report and leave
catalog support unknown. Only an explicit feature-specific rejection is unsupported.

## Partial refreshes must not publish

A sequential refresh can write several catalogs and fail on the next provider, leaving a
plausible mixed snapshot. Run `refresh.py`, which performs every phase against an isolated
taxonomy root and publishes only after validation succeeds.
