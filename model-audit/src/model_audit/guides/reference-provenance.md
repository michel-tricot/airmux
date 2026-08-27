# Provenance

The catalog is only useful if a reader can tell a measured fact from a borrowed one. Every
rule here exists so that distinction survives.

## null means the vendor does not say

Not absent. Not unsupported. Not zero. Three quarters of providers publish no capability
metadata at all, so nulls are common and load-bearing.

A reader that treats null as false will conclude Anthropic's models have no context window.
Where a value genuinely cannot exist, say so differently: non-text models are excluded from
the catalog rather than carrying nulls.

## Model catalogs carry `source_type`

- `api`: fetched from the provider's own listing endpoint. Authoritative
- `docs`: transcribed from a models or pricing page, or from a spec enum. Goes stale the
  moment a model ships

Provider synchronization never replaces a successful API catalog with documentation-only
data. `api` always wins.

## Limits carry `limits_source`

- `provider`: the provider's own listing returned it
- `openrouter-index`: borrowed from OpenRouter's cross-provider index. Correct for the
  model, possibly not for this host's serving configuration
- `vendor-docs`: hand-transcribed from the vendor's model page

The distinction matters because serving limits differ per host. The same open-weights model
is served at different context lengths by different providers, so a borrowed limit is a
good default and a bad guarantee.

## Parameter support carries separate evidence

`parameter_evidence.model_discovery` is generated for every model from the request schemas
declared by its provider. Its source list points to those exact schema files. A field present
in a schema is supported; an absent field remains unknown because permissive and
documentation-derived schemas cannot prove rejection.

`airllm-audit providers sync` adds discovery evidence after acquiring models and schemas.
Catalog validation independently regenerates the schema-derived evidence and rejects missing
or stale model records. Live behavioral support belongs in accepted audit evidence, never in
the model catalog. There is no maintained list of model ids or parameter claims in the skill.

## Schemas carry provenance in the filename

`<ingress>.<id>.<part>.json`. A file named for the provider is that provider's own schema.
An entry pointing at `oai.openai.*` or `anthropic.anthropic.*` from a different provider
means that vendor publishes no parameters of its own and only claims SDK compatibility.

Six providers are in that group: nvidia, hyperbolic, lambda, baseten, bedrock, vertex, plus
the Anthropic surfaces of deepseek and minimax.

**They must be excluded from agreement counts.** Six providers echoing OpenAI's schema is
one fact repeated six times, not six providers agreeing. `field_matrix.py` emits a separate
`supported_by_excluding_standins` column for exactly this, and the HTML report flags those
columns amber.

Treat a stand-in as an upper bound and expect silent parameter dropping.

## Doc-derived schemas are permissive by construction

They set `additionalProperties: true`, because a parameter table shows what a vendor chose
to document and never what the API rejects. A spec-derived schema can be strict; a
doc-derived one cannot honestly be.

`x-notes` carries what a schema cannot express: MiniMax accepts `frequency_penalty` and
ignores it, Gemini silently drops anything undocumented, SambaNova documents
`presence_penalty` as not currently implemented. These are the facts that break adapters,
and they are invisible to validation.

## Absence of a part is not absence of the thing

A schema entry lists `request`, `response` and `stream` only where the vendor's spec
declares them. Most specs declare a request and a 200 body and leave SSE framing to prose.
A missing `stream` means undocumented, not unstreamable.

## Known gaps are recorded, not tolerated

`validate.py` fails when a wire ingress has no schema, unless the pair is in `KNOWN_GAPS`
with a reason. Bedrock's Converse surface is there because AWS publishes a Smithy service
model rather than OpenAPI.

Add the reason. Do not delete the check.

## updated is a change date, not a check date

Catalogs carry `updated`, the date the content last changed. Rerunning against a vendor
that returned exactly what it returned last time leaves the file untouched, stamp included.

The catalog deliberately does not record when it was last checked. That field would move on
every run, every file would look modified daily, and a reviewer would learn to skim past the
diffs that matter. If you need to know when a fact was last confirmed, rerun and read what
moved.
