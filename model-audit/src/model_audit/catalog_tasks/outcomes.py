from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path


class UnknownProvidersError(ValueError):
    def __init__(self, providers: set[str], location: Literal["providers.yml", "taxonomy/models", "provider catalog"]) -> None:
        self.providers = tuple(sorted(providers))
        self.location = location
        super().__init__(f"not in {location}: {list(self.providers)}")


class MissingProviderSourceError(ValueError):
    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"active provider {provider} has no typed provider source")


@dataclass(frozen=True)
class CatalogCount:
    kind: Literal["providers", "routers", "candidates"]
    entries: int


@dataclass(frozen=True)
class SeedWritten:
    path: Path
    counts: tuple[CatalogCount, ...]


@dataclass(frozen=True)
class CatalogFile:
    path: Path
    entries: int


@dataclass(frozen=True)
class CatalogRestored:
    files: tuple[CatalogFile, ...]


@dataclass(frozen=True)
class ParametersDiscovered:
    models: int
    catalogs_changed: int


@dataclass(frozen=True)
class FetchedModels:
    provider: str
    models: int
    declared: int
    new: int


@dataclass(frozen=True)
class SkippedModels:
    provider: str
    reason: str


@dataclass(frozen=True)
class ModelFetchFailed:
    provider: str
    reason: str


type ModelAcquisition = FetchedModels | SkippedModels | ModelFetchFailed


@dataclass(frozen=True)
class ModelsFetched:
    results: tuple[ModelAcquisition, ...]
    required: bool

    @property
    def failed(self) -> bool:
        return any(isinstance(result, ModelFetchFailed) or (self.required and isinstance(result, SkippedModels)) for result in self.results)


@dataclass(frozen=True)
class DocumentedSchema:
    name: str
    properties: int
    required: tuple[str, ...]


@dataclass(frozen=True)
class SchemasDocumented:
    schemas: tuple[DocumentedSchema, ...]


@dataclass(frozen=True)
class ExtractedPart:
    kind: Literal["request", "response", "stream"]
    size_bytes: int


@dataclass(frozen=True)
class ExtractedSchema:
    provider: str
    ingress: str
    parts: tuple[ExtractedPart, ...]


@dataclass(frozen=True)
class SkippedSchema:
    provider: str
    ingress: str
    reason: Literal["candidate", "path_not_found"]


@dataclass(frozen=True)
class SchemaFetchFailed:
    provider: str
    ingress: str
    reason: str


@dataclass(frozen=True)
class SchemasExtracted:
    schemas: tuple[ExtractedSchema | SkippedSchema | SchemaFetchFailed, ...]


@dataclass(frozen=True)
class IconsFetched:
    written: tuple[str, ...]
    generated: tuple[str, ...]
    missing: tuple[str, ...]
    failures: tuple[tuple[str, str], ...]
    version: str


@dataclass(frozen=True)
class CatalogEnriched:
    models: int
    limits: int
    priced: int
    prices: tuple[tuple[str, int], ...]
    missing_metadata: int
    missing_catalogs: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ValidationFailed:
    problems: tuple[str, ...]


@dataclass(frozen=True)
class CatalogValidated:
    entries: int
    schemas: int
    icons: int
    models: int
    complete: int


@dataclass(frozen=True)
class FieldMatrixWritten:
    ingress: Literal["oai", "anthropic"]
    max_depth: int
    columns: int
    standins: int
    paths: int
    universal: int
    solo: int
    csv_path: Path


@dataclass(frozen=True)
class ReportWritten:
    path: Path
    size_bytes: int


type CatalogOutcome = (
    SeedWritten
    | CatalogRestored
    | ParametersDiscovered
    | ModelsFetched
    | SchemasDocumented
    | SchemasExtracted
    | IconsFetched
    | CatalogEnriched
    | ValidationFailed
    | CatalogValidated
    | FieldMatrixWritten
    | ReportWritten
)
