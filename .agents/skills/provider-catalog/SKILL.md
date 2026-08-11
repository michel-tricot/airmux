---
name: provider-catalog
description: Research and maintain the LLM provider catalog under taxonomy/: adding a provider or router, refreshing model lists, extracting request and response schemas, or answering "what does provider X accept". Use whenever a task involves what a provider's API looks like, what models it serves, how it authenticates, or whether a claim about a provider is still true.
user-invocable: true
---

# Provider catalog

`taxonomy/` is a researched catalog of LLM providers and routers: what wire shape each one
accepts, how it authenticates, what models it serves, and the JSON Schema of its completion
request and response. It is research input for adapter planning. It is never loaded at
runtime; `taxonomy.yml` at the repo root is the file `airllmcp taxonomy` reads.

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
    fetch_models.py        model catalogs from each provider's listing endpoint
    doc_models.py          model catalogs transcribed where no endpoint is reachable
    enrich_limits.py       fills context_length and max_output_tokens
    fetch_icons.py         vendors provider marks as SVG
    field_matrix.py        field support matrix, per ingress
    build_report.py        renders the matrix to HTML
    validate.py            structural gates, run after every change

taxonomy/
  providers.yml            one entry per provider, 12 fields, uniform
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
python doc_models.py                    # transcribed lists, never overwrites api ones
python enrich_limits.py                 # fills limits, records provenance
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

`field_matrix.py` flattens every provider's request schema into JSONPaths and writes, per
ingress, a CSV for spreadsheet use and a JSON blob. `build_report.py` renders both into one
self-contained HTML page at `taxonomy/reports/field-matrix.html`, green for accepted and red
for absent, sortable and filterable, with OpenRouter as the leading column because a router
accepts the widest surface.

Two columns count support: `supported_by`, and `supported_by_excluding_standins` which drops
the six providers that borrow the canonical schema. Use the second for any claim about
consensus; six providers echoing OpenAI is one fact repeated, not six providers agreeing.

Depth 2 is the useful default. Depth 1 gives 255 paths and reads as a summary; depth 3 gives
521 and is mostly OpenRouter's nested routing options.

Rerun after any schema change. It is not automatic.

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
