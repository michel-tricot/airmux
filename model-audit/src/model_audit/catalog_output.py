from __future__ import annotations

from typing import assert_never

from model_audit.catalog_tasks.outcomes import (
    CatalogEnriched,
    CatalogOutcome,
    CatalogRestored,
    CatalogValidated,
    ExtractedSchema,
    FetchedModels,
    FieldMatrixWritten,
    IconsFetched,
    ModelAcquisition,
    ModelFetchFailed,
    ModelsFetched,
    ParametersDiscovered,
    ReportWritten,
    SchemaFetchFailed,
    SchemasDocumented,
    SchemasExtracted,
    SeedWritten,
    SkippedModels,
    SkippedSchema,
    ValidationFailed,
)


def failed(outcome: CatalogOutcome) -> bool:
    match outcome:
        case ModelsFetched():
            return outcome.failed
        case IconsFetched():
            return bool(outcome.failures)
        case ValidationFailed():
            return True
        case _:
            return False


def _model_line(acquisition: ModelAcquisition) -> str:
    match acquisition:
        case FetchedModels():
            status = "ok"
            detail = f"{acquisition.models:>4} models, {acquisition.declared:>4} declared, {acquisition.new:>3} new"
        case SkippedModels():
            status, detail = "skip", acquisition.reason
        case ModelFetchFailed():
            status, detail = "fail", acquisition.reason
        case _:
            assert_never(acquisition)
    return f"  {status:<7} {acquisition.provider:<13} {detail}"


def _schema_line(schema: ExtractedSchema | SkippedSchema | SchemaFetchFailed) -> str:
    match schema:
        case ExtractedSchema():
            detail = ", ".join(f"{part.kind}:{part.size_bytes // 1024}k" for part in schema.parts) or "nothing extractable"
        case SkippedSchema():
            detail = "candidate, spec recorded but not extracted" if schema.reason == "candidate" else "path not found"
        case SchemaFetchFailed():
            detail = f"FETCH FAIL {schema.reason}"
        case _:
            assert_never(schema)
    return f"  {schema.provider:<14} {schema.ingress:<10} {detail}"


def lines(outcome: CatalogOutcome) -> tuple[str, ...]:  # noqa: PLR0911, PLR0912 each catalog outcome has its own CLI presentation
    match outcome:
        case SeedWritten():
            counts = ", ".join(f"{count.entries} {count.kind}" for count in outcome.counts)
            return (f"wrote {outcome.path} ({counts})",)
        case CatalogRestored():
            return tuple(f"  wrote {catalog.path.relative_to(catalog.path.parent.parent)} ({catalog.entries} entries)" for catalog in outcome.files)
        case ParametersDiscovered():
            return (f"parameter support discovered for {outcome.models} models; {outcome.catalogs_changed} catalogs changed",)
        case ModelsFetched():
            written = sum(isinstance(result, FetchedModels) for result in outcome.results)
            skipped = sum(isinstance(result, SkippedModels) for result in outcome.results)
            failures = sum(isinstance(result, ModelFetchFailed) for result in outcome.results)
            return (*(_model_line(result) for result in outcome.results), "", f"{written} written, {skipped} skipped, {failures} failed")
        case SchemasDocumented():
            return (
                *(f"{schema.name}: props={schema.properties} required={list(schema.required)}" for schema in outcome.schemas),
                "",
                f"wrote {len(outcome.schemas)} documentation-derived schemas",
            )
        case SchemasExtracted():
            return tuple(_schema_line(schema) for schema in outcome.schemas)
        case IconsFetched():
            return (
                f"  {len(outcome.written)} marks written to taxonomy/icons at lobehub {outcome.version}",
                *(
                    (f"  {len(outcome.generated)} generated as a monogram, no mark upstream: {', '.join(outcome.generated)}",)
                    if outcome.generated
                    else ()
                ),
                *((f"  entries missing an icon field: {', '.join(outcome.missing)}",) if outcome.missing else ()),
                *(f"  FAIL {slug}: {reason}" for slug, reason in outcome.failures),
            )
        case CatalogEnriched():
            return (
                *(f"  models.dev has no catalog for {provider} (looked under {key!r})" for provider, key in outcome.missing_catalogs),
                f"models: {outcome.models}",
                f"  with both limits : {outcome.limits}",
                f"  with pricing     : {outcome.priced}",
                *(f"    {source:<28} {count}" for source, count in outcome.prices),
                f"  models with missing metadata: {outcome.missing_metadata}",
            )
        case ValidationFailed():
            return (f"{len(outcome.problems)} problems", "", *(f"  {problem}" for problem in outcome.problems))
        case CatalogValidated():
            return (
                (
                    f"ok: {outcome.entries} entries, {outcome.schemas} schemas, {outcome.icons} icons, "
                    f"{outcome.models} models ({outcome.complete} with both limits)"
                ),
            )
        case FieldMatrixWritten():
            return (
                f"ingress {outcome.ingress} | depth {outcome.max_depth}",
                f"  {outcome.columns} columns ({outcome.standins} canonical stand-ins), {outcome.paths} paths",
                f"  universal: {outcome.universal} | single-column: {outcome.solo}",
                f"  wrote {outcome.csv_path} and {outcome.csv_path.with_suffix('.json')}",
            )
        case ReportWritten():
            return (f"wrote {outcome.path} ({outcome.size_bytes:,} bytes)",)
        case _:
            assert_never(outcome)
