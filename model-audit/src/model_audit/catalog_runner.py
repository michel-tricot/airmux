from __future__ import annotations

import traceback
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from enum import StrEnum
from io import StringIO
from typing import TYPE_CHECKING, Literal

from model_audit.catalog_ops import ProviderSource, add_provider, provider_sources
from model_audit.catalog_tasks import (
    bootstrap,
    discover_parameters,
    doc_schemas,
    enrich,
    extract_schemas,
    fetch_icons,
    fetch_models,
    make_seed,
    validate,
)
from model_audit.taxonomy import write as write_taxonomy

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

type SyncComponent = Literal["models", "pricing", "schemas", "parameters", "icons"]
type SyncStepComponent = Literal["definition", "seed", "models", "pricing", "schemas", "parameters", "icons", "taxonomy", "validation"]
type SyncStatus = Literal["completed", "failed"]


class CatalogTask(StrEnum):
    bootstrap = "bootstrap"
    discover_parameters = "discover_parameters"
    doc_schemas = "doc_schemas"
    enrich = "enrich"
    extract_schemas = "extract_schemas"
    fetch_icons = "fetch_icons"
    fetch_models = "fetch_models"
    make_seed = "make_seed"
    validate = "validate"


@dataclass(frozen=True)
class CatalogTaskResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class CatalogSyncStep:
    provider: str
    component: SyncStepComponent
    detail: str
    returncode: int = 0

    @property
    def status(self) -> SyncStatus:
        return "completed" if self.returncode == 0 else "failed"


CatalogMain = Callable[[Sequence[str]], int]

TASKS: dict[CatalogTask, CatalogMain] = {
    CatalogTask.bootstrap: bootstrap.main,
    CatalogTask.discover_parameters: discover_parameters.main,
    CatalogTask.doc_schemas: doc_schemas.main,
    CatalogTask.enrich: enrich.main,
    CatalogTask.extract_schemas: extract_schemas.main,
    CatalogTask.fetch_icons: fetch_icons.main,
    CatalogTask.fetch_models: fetch_models.main,
    CatalogTask.make_seed: make_seed.main,
    CatalogTask.validate: validate.main,
}


def run_catalog_task(task: CatalogTask, *arguments: str) -> CatalogTaskResult:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            returncode = TASKS[task](arguments)
        except Exception as error:  # noqa: BLE001 catalog task failures become structured CLI results
            traceback.print_exception(error, file=stderr)
            returncode = 1
    return CatalogTaskResult(returncode=returncode, stdout=stdout.getvalue(), stderr=stderr.getvalue())


def _detail(result: CatalogTaskResult) -> str:
    lines = [line.strip() for line in (result.stdout or result.stderr).splitlines() if line.strip()]
    return "; ".join(lines[-3:]) or "completed"


def _sync_tasks(provider: str, components: tuple[SyncComponent, ...]) -> tuple[tuple[SyncStepComponent, CatalogTask, tuple[str, ...]], ...]:
    selected = frozenset(components)
    tasks: tuple[tuple[SyncStepComponent, CatalogTask, tuple[str, ...], bool], ...] = (
        ("schemas", CatalogTask.extract_schemas, (provider,), "schemas" in selected),
        ("schemas", CatalogTask.doc_schemas, (provider,), "schemas" in selected),
        ("schemas", CatalogTask.bootstrap, ("--yaml",), "schemas" in selected),
        ("models", CatalogTask.fetch_models, (provider,), bool(selected & {"models", "pricing"})),
        ("pricing", CatalogTask.enrich, (provider,), bool(selected & {"models", "pricing"})),
        ("parameters", CatalogTask.discover_parameters, (provider,), "parameters" in selected or bool(selected & {"models", "schemas"})),
        ("icons", CatalogTask.fetch_icons, (provider,), "icons" in selected),
    )
    return tuple((component, task, arguments) for component, task, arguments, included in tasks if included)


def _run_sync_task(provider: str, component: SyncStepComponent, task: CatalogTask, arguments: tuple[str, ...] = ()) -> CatalogSyncStep:
    result = run_catalog_task(task, *arguments)
    return CatalogSyncStep(provider=provider, component=component, detail=_detail(result), returncode=result.returncode)


def _finish_sync(root: Path, provider: str) -> tuple[CatalogSyncStep, CatalogSyncStep]:
    providers, models, changed = write_taxonomy(root)
    validation = _run_sync_task(provider, "validation", CatalogTask.validate)
    return (
        CatalogSyncStep(
            provider=provider,
            component="taxonomy",
            detail=f"{providers} providers, {models} models; {'written' if changed else 'current'}",
        ),
        validation,
    )


def _sync_provider(
    root: Path,
    provider: str,
    source: ProviderSource | None,
    components: tuple[SyncComponent, ...],
    *,
    finalize: bool,
) -> Iterator[CatalogSyncStep]:
    if source is not None and source.definition is not None:
        add_provider(root, source.definition, replace=True)
    seed = _run_sync_task(provider, "seed", CatalogTask.make_seed)
    yield seed
    if seed.returncode:
        return
    for component, task, arguments in _sync_tasks(provider, components):
        step = _run_sync_task(provider, component, task, arguments)
        yield step
        if step.returncode:
            return
    if finalize:
        yield from _finish_sync(root, provider)


def sync_catalog(
    root: Path,
    providers: Sequence[str],
    components: tuple[SyncComponent, ...],
    *,
    refresh_definitions: bool = True,
) -> tuple[CatalogSyncStep, ...]:
    selected = tuple(providers)
    sources = provider_sources() if refresh_definitions else {}
    steps = tuple(
        step for provider in selected for step in _sync_provider(root, provider, sources.get(provider), components, finalize=len(selected) == 1)
    )
    return steps if len(selected) == 1 else (*steps, *_finish_sync(root, "all"))
