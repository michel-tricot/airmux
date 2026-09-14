from __future__ import annotations

import traceback
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from enum import StrEnum
from io import StringIO

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
