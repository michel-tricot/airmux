# Field reference

Typed provider sources define providers. `providers.yml` and `routers.yml` are applied data
projections. Every projected field is defined here.

Both files hold the same 12 fields in the same order, so a router is readable by anything
that reads a provider.

## id, name

`id` is the key used everywhere: schema filenames, model catalog filenames, matrix columns.
Lowercase, hyphenated. `name` is the vendor's own name for itself and may be renamed under
them; when a product is renamed keep the id if that is still what the endpoint is called.
Vertex is `vertex`, named `Gemini Enterprise Agent Platform`, and still answers on
`aiplatform.googleapis.com`.

## icon_mono, icon_color

Slugs in `@lobehub/icons-static-svg` 1.94.0 (MIT), vendored to `taxonomy/icons/{slug}.svg`.
Neither is ever empty, so a consumer never branches on a missing icon.

- `icon_mono` is `fill="currentColor"`, inherits the surrounding colour, works on any
  ground. The right default for a themed surface
- `icon_color` is the brand mark with colours baked in, so it does not follow the theme.
  Twelve vendors have no colour variant upstream; for those this names the monochrome slug

Reka has no mark upstream at all, so both fields name a generated monogram, written by
`airllm-audit providers sync <provider> --only icons` on a 404. It is the only file under
`icons/` not traceable to lobehub.

Normalization: width, height and the upstream flex styling dropped so the consumer owns
sizing and layout; titles dropped so it owns the accessible name; every local id namespaced
`airllm-{slug}-` so two marks on one page cannot collide on a gradient id. It is markup,
not data: whatever renders it sanitizes it.

## homepage, docs

The vendor's product page and the top level of its API documentation. Both are recorded
post-redirect, because these hosts migrate often.

## base_url

The inference endpoint, which is what the applied `taxonomy/taxonomy.yml` routes to. Distinct from
`models_url`: Groq lists at `/openai/v1/models` and infers at `/openai/v1`, and the two are
not always one path apart. Candidates have no base_url, because nothing routes to them.

## openapi

A machine-readable spec that parses and contains the inference paths, checked rather than
assumed. `null` means none could be found, with the reason as a YAML comment on the entry.

Stainless-generated SDKs publish a content-addressed spec whose URL changes on every
regeneration, so those entries point at the `.stats.yml` that names the current one rather
than at a URL that will rot.

## models_url

The model listing endpoint. It must agree with the provider source acquisition URL. A URL
containing `{...}` is account-scoped and cannot be fetched without substitution; sync
reports the template instead of failing.

## ingress

The request shape the provider's own API accepts, one or more of:

| value | meaning |
|---|---|
| `oai` | OpenAI Chat Completions |
| `oai_responses` | OpenAI Responses. Only split out where a vendor serves both as separate paths, which so far is only OpenRouter |
| `anthropic` | Anthropic Messages |
| `google` | Gemini `generateContent` |
| `other_standard` | a widely adopted third-party shape. Currently unused |
| `custom` | a shape only this vendor speaks |

Two values mean it serves both, so one adapter can cover several entries.

## auth

How the credential rides on the request, one or more of:

| value | meaning |
|---|---|
| `bearer` | `Authorization: Bearer <key>` |
| `header_key:<name>` | a vendor-specific header carries the key, named after the colon exactly as the vendor documents it. HTTP header names are case-insensitive, so the casing is provenance, not a constraint |
| `sigv4` | AWS SigV4 request signing |
| `oauth` | an access token minted from a service account or directory identity |

Two values mean two accepted mechanisms, which is not the same as two surfaces. Gemini
takes `x-goog-api-key` natively and bearer on its OpenAI-compatible layer; DeepSeek takes
bearer on the OpenAI surface and `x-api-key` on the Anthropic one; bedrock, vertex and
azure-foundry each accept a full-strength mechanism plus a weaker key shortcut.

The field says nothing about what else a request needs. See account scoping below.

## env_var

The conventional environment variable for the credential, as the vendor's own SDK reads it.
Not guessable: Cohere is `CO_API_KEY`, Replicate is `REPLICATE_API_TOKEN`, Hugging Face is
`HF_TOKEN`, Bedrock is `AWS_BEARER_TOKEN_BEDROCK`.

## schema

Keyed by API kind, then ingress, then part. See `provenance.md` for what the filenames mean
and why stand-ins are excluded from consensus counts.

# Scope

## What is in

Providers reachable with an API key alone: no cloud account, IAM role, project id, region
binding or sales contact.

Four platforms are in despite needing more than a key, and each needs something different:

- **bedrock** an AWS account, a region, per-model access enablement, and either a Bedrock
  API key (bearer, chat completions only) or SigV4
- **azure-foundry** a subscription and a named deployment. The deployment name is the model,
  and `api-version` is a required query parameter, which is why `$.model` is absent from its
  request schema
- **vertex** a GCP project and region, service account OAuth or an express-mode key
- **huggingface** a token alone, but it is a router in front of partner providers already
  listed here, so entries overlap by construction

## What is out

- **Routers and gateways**: OpenRouter, Vercel AI Gateway, Portkey, Requesty, AI/ML API.
  OpenRouter lives in `routers.yml`; the others are not catalogued yet
- **Other clouds needing account-scoped config**: watsonx, OCI, Databricks, Snowflake,
  Cloudflare, Scaleway, OVHcloud
- **Regional KYC or enterprise gating**: Volcano Engine, Baidu Qianfan, Tencent Hunyuan,
  Alibaba Model Studio, Aleph Alpha, Meta Llama API

Adding any of these is a scope decision, not a data-entry task. Say so before doing it.
