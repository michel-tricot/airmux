---
name: provider-catalog
description: Research and maintain the LLM provider catalog under taxonomy/: adding a provider or router, refreshing model lists, extracting request and response schemas, or answering "what does provider X accept". Use whenever a task involves what a provider's API looks like, what models it serves, how it authenticates, or whether a claim about a provider is still true.
user-invocable: true
---

# Provider catalog

`taxonomy/` is a researched catalog of LLM providers and routers: what wire shape each one
accepts, how it authenticates, what models it serves, and the JSON Schema of its completion
request and response. It is research input for adapter planning. It is never loaded at
runtime; `taxonomy/taxonomy.yml` is the generated file `airllmcp taxonomy` reads.

## Active versus candidate

`providers.yml` holds only providers validated with a working account. Everything else is
in `candidates.yml` with five fields: id, name, homepage, docs, env_var. Candidates carry
no schemas, no model catalogs and no icons, and nothing fetches them.

The split exists because unvalidated data is worse than absent data. A doc-derived catalog
looks the same in a diff as a live one and is wrong in ways nobody notices: Fireworks
advertised 297 models and serves 20, Together advertised 24 and serves 74.

To promote a candidate: move its entry to `providers.yml` with the full field set, add a
module under `scripts/sources/`, run the extractors and `make_seed.py`. Everything derived
comes back in minutes. Demoting is the reverse, and `validate.py` fails if an id is in both
files or if a candidate still has derived data.

nvidia is a candidate for a different reason. It was validated, and a key proved its API
publishes nothing beyond model ids, so it is parked rather than dropped.

## The rule that matters most

Never write a fact you have not fetched. Model names, base URLs, auth headers and context
windows all drift faster than any training cutoff, and a plausible wrong value is worse
than an absent one because nothing downstream will question it. Treat everything you
remember about a provider as a hypothesis to check, including things this file says.

When a check fails to settle a question, the answer is a null and a note, never a guess.

## Layout

The tooling lives with this skill; the catalog is its output. Nothing executable sits inside
`taxonomy/`, so the directory can be deleted and rebuilt.

```
.agents/skills/provider-catalog/
  seed.yml                 the irreplaceable half: which providers exist and where their
                           facts live. Generated from the catalog, never hand-edited
  scripts/
    paths.py               finds the repo root, so scripts run from any directory
    canonical.py           deterministic key order, list order and change stamps
    bootstrap.py           rebuilds taxonomy/ from seed.yml
    make_seed.py           regenerates seed.yml from the catalog
    extract_schemas.py     request/response/stream out of vendor OpenAPI specs
    doc_schemas.py         request schemas transcribed where there is no spec
    model_kind.py          text vs embedding/image/audio/rerank classifier
    fetch_models.py        drives the sources registry and writes the catalogs
    sources/               one module per provider, see sources/base.py
      base.py              ModelSource, the registry, and the shared helpers
      groq.py              pricing, modalities, supported_features
      anthropic.py         limits plus the nested capabilities tree
      openai.py            bare ids and shutdown_date, nothing more exists
      fireworks.py         serverless-only, control plane, UNVERIFIED
      openai_shaped.py     novita, deepinfra, sambanova, huggingface, nvidia
    enrich.py              fills limits and pricing from secondary sources
    discover_parameters.py derives each model's parameter baseline from its provider request schemas
    probe_parameters.py    tests parameters against live model endpoints; conclusive probes win
    fetch_icons.py         vendors provider marks as SVG
    field_matrix.py        field support matrix, per ingress
    build_report.py        renders the matrix to HTML
    build_taxonomy.py      regenerates taxonomy/taxonomy.yml, the applied file
    validate.py            structural gates, run after every change

taxonomy/
  providers.yml            validated providers only, 12 fields, uniform
  candidates.yml           everything else, identity only, never fetched
  routers.yml              same shape, for services that dispatch to others
  schemas/completion/      <ingress>.<id>.<part>.json
  models/                  <id>.json, text models only
  icons/                   <slug>.svg
  reports/                 CSV, JSON and HTML field matrix
```

`taxonomy/providers.yml` and `routers.yml` are the source of truth and carry data only;
`references/fields.md` defines every field. `seed.yml` is a projection of them minus
`schema`, which is derived. `validate.py` fails when the two disagree, so the seed cannot
rot.

## Workflows

### Adding a model source

One new module under `scripts/sources/`. Subclass `ModelSource`, set `id` and `url`,
implement `normalize`. Override `items` when the payload is not `{"data": [...]}` and
`fetch` when one request is not enough. Touch no other file: the registry is a subclass
walk, so a module that exists is a module that runs.

Map every field by hand. A generic normalizer holds only the intersection of what vendors
publish, which is close to nothing: Groq returns pricing and a feature list, Anthropic a
capabilities tree, OpenAI four fields. Flattening those loses most of the catalog's value.

Put the per-provider instructions in the module docstring. Which endpoint is the real
catalog, what serverless means for that vendor, which fields lie, what state the account
has to be in. That is knowledge nobody recovers by reading code.

Return `None` from `normalize` for anything the account cannot call without provisioning.
The catalog answers "what can airllm route to today", so a model that needs a deployment
spun up does not belong in it.

### Adding a provider

1. Find its OpenAPI spec before anything else. `references/sources.md` lists the locations
   worth trying and the SDK trick that finds Stainless-hosted specs
2. Add the entry to `providers.yml` with all 12 fields. `null` is allowed for `openapi`
   only; everything else must resolve. `icon_mono` and `icon_color` are both required, and
   `icon_color` names the monochrome slug when the vendor has no colour variant
3. Extract request, response and stream schemas from the spec. Where there is no spec,
   transcribe the vendor's parameter table and set `additionalProperties: true`, because a
   parameter table is evidence of what is accepted and never of what is rejected
4. Determine `auth` from the spec's `securitySchemes`, or probe it: send a deliberately
   invalid key and read which header the error names
5. `python scripts/fetch_icons.py` to vendor the mark
6. `python scripts/make_seed.py` so a rebuild keeps the new provider
7. `python scripts/validate.py` until clean

### Rebuilding from scratch

```
python .agents/skills/provider-catalog/scripts/bootstrap.py
```

Restores both YAML files from the seed, re-extracts every schema from the vendors' live
specs, re-vendors the icons, refetches the model catalogs, refills the limits, and rebuilds
the reports. Verified by deleting `taxonomy/` outright: schema files, model catalogs, icons,
catalog data, schema wiring and model counts all came back identical.

The rebuild is byte-faithful: the YAML files carry data only, so what comes back is what
was there. The one thing that legitimately changes is coverage. A provider whose vendor has
since moved or withdrawn its spec yields a smaller catalog rather than a broken one, which
is correct behaviour and worth reading the output for.

### Refreshing model catalogs

```
cd .agents/skills/provider-catalog/scripts
python fetch_models.py [provider ...]   # needs the provider's env_var
python enrich.py                        # fills limits and pricing, records provenance
python validate.py
```

`fetch_models.py` reads the endpoint and credential name from `providers.yml`, so neither
is written down twice. A provider whose key is absent is skipped and named, so a partial
run is legible rather than silently thin.

### Regenerating the field support report

```
cd .agents/skills/provider-catalog/scripts
python field_matrix.py oai 2        # ingress, then how deep to walk nested objects
python field_matrix.py anthropic 2
python build_report.py
```

`field_matrix.py` flattens AirLLM's canonical request schema and every provider's request
schema into JSONPaths and writes, per ingress, a CSV for spreadsheet use and a JSON blob.
`build_report.py` renders both into one self-contained HTML page at
`taxonomy/reports/field-matrix.html`, green for accepted and red for absent, sortable and
filterable, with AirLLM as the leading column.

Two columns count support: `supported_by`, and `supported_by_excluding_standins` which drops
AirLLM and providers that borrow another provider's canonical schema. Use the second for any
claim about provider consensus; repeated schemas are one fact, not independent agreement.

Depth 2 is the useful default. Depth 1 reads as a summary, while depth 3 expands deeply nested
request objects.

Rerun after any schema change. It is not automatic.

### Regenerating the applied taxonomy

```
python build_taxonomy.py            # write taxonomy/taxonomy.yml
python build_taxonomy.py --check    # fail if stale, for CI
```

`taxonomy/` holds both halves: providers.yml and the derived data are research, and
`taxonomy/taxonomy.yml` is what `airllmcp taxonomy` applies to the database. The second is generated from the first, so never hand-edit it.
`validate.py` fails when the two have drifted, and `bootstrap.py` regenerates it last.

### Refreshing parameter support

Parameter support is part of model discovery, never a hand-maintained model list. A model
record receives its baseline from the provider request schemas used by the gateway. Schema
presence means supported; schema absence stays unknown. `fetch_models.py` applies that
baseline before writing and probes newly returned models when its provider credential is
available. `validate.py` recomputes the baseline and rejects every stale or unclassified
model, so adding a model by any other path cannot bypass the workflow.

To backfill existing catalogs or refresh live evidence explicitly:

```
cd .agents/skills/provider-catalog/scripts
python discover_parameters.py
python probe_parameters.py openai --parameter=temperature
python build_taxonomy.py
python validate.py
```

The manual probe command selects only models emitted in `taxonomy.yml`. Probe values are
deliberately non-default so a model that merely permits a fixed default is not classified
as supporting a configurable parameter.

The model catalog keeps schema-discovery and live-probe evidence separately. Probe attempts
are recorded even when their result is inconclusive, while only conclusive results affect
runtime support. A conclusive live probe always wins for the same model, endpoint and
canonical parameter. Success means supported; only an explicit unsupported-parameter
response means unsupported. Authentication, access, rate-limit, timeout and generic
bad-request results leave support unknown.

Model ids are always `<provider>/<upstream>`. `gpt-oss-120b` is served by both Groq and
Together at different prices and limits, so a bare id cannot be the caller-facing key, and
prefixing only on collision would rename existing models whenever a provider is added.
`upstream_model` carries the name that goes on the wire.

A model with no context window is skipped rather than emitted. `ModelIn` defaults
`context_window` to 128000, and writing that default for an unknown window would invent a
routing limit. The run prints how many were skipped.

### Answering a question about a provider

Read the catalog first, then verify the specific claim against the vendor before repeating
it. The catalog records when it was checked; it does not stay true on its own.

## Rules the data obeys

- **`null` means the vendor does not say.** It never means absent, unsupported or zero.
  Anything that reads this catalog must treat null as unknown
- **Provenance travels with the value.** `source_type` on model catalogs, `limits_source`
  on limits, and for schemas the filename: a file named for the provider is its own, one
  named for another provider is a compatibility claim standing in
- **Six providers publish no parameters of their own** and borrow the canonical schema.
  They are not evidence of consensus and must be excluded from agreement counts
- **The catalog is text models only.** `model_kind.py` drops embeddings, rerankers, image,
  video, speech and OCR models at collection, because a context window and a max output
  token count are undefined for them
- **Every entry resolves to both a monochrome and a colour mark.** `icon_mono` uses
  `currentColor` and follows the theme; `icon_color` falls back to the monochrome slug
  where no colour variant exists, and to a generated monogram where no mark exists at all.
  Neither field is ever null, so consumers never branch on a missing icon
- **Output is deterministic, because it gets reviewed in a diff.** Model lists sort by id,
  record keys follow a fixed order, `$defs` sort alphabetically, and `updated` is the date
  content last *changed* rather than the date it was last checked. Two consecutive full
  runs produce byte-identical files, so anything that shows in a diff is a real change
- **A provider without a module is not fetched.** `fetch_models.py` skips it and says so,
  rather than guessing at its shape. Doc-derived catalogs still cover those providers
- **No prices are hardcoded in a module.** A frozen table is wrong twice over: it stops
  tracking the vendor the day it is written, and because it is set inside a source module
  every value gets stamped `pricing_source: provider`, claiming an authority it does not
  have. Prices come from the provider's API or from `enrich.py`, never from a literal
- **Gaps are filled from ranked sources, never invented.** The provider's own value wins
  and is never overwritten. models.dev fills next, and is preferred over OpenRouter because
  it is keyed by provider, so a Fireworks price is Fireworks' price rather than someone
  else's for the same weights. The OpenRouter index fills last and is marked, because it is
  one entry per model rather than per host. `limits_source` and `pricing_source` are
  separate, since a record commonly has an authoritative limit and a borrowed price
- **Refetching never discards enrichment.** `fetch_models.py` carries forward the fields
  only `enrich_limits.py` can supply, so a refresh does not undo a limits pass
- **One source of truth per fact.** Endpoints and credential names live in the YAML;
  scripts read them. Never copy either into a script
- **Nothing executable lives in taxonomy/.** It is output. A generator that writes itself
  into its own output cannot survive a rebuild

`references/provenance.md` has the full reasoning.

## Before you finish

`python scripts/validate.py` must exit clean. It checks field uniformity, vocabularies,
credential collisions, icon references, schema naming, that every schema parses and
compiles, that nothing is orphaned or dangling, and that model catalogs stay text-only with
consistent counts. It catches the drift that hand-checking misses; it found a real
regression the first time it ran.

A wire ingress with no schema fails unless it is listed in `KNOWN_GAPS` with a reason.
Add the reason rather than deleting the check.

## Reading

- `references/fields.md` for what every field means, the vocabularies, and what is in scope
- `references/sources.md` for where specs live, in preference order, and how to find them
- `references/traps.md` for the failure modes that cost a round trip each, with symptoms
- `references/provenance.md` for what null means, stand-ins, and why counts exclude them
