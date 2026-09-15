from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from model_audit import catalog_runner
from model_audit.catalog_runner import CatalogTaskResult, sync_catalog

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("components", "tasks"),
    [
        (("pricing",), ("make_seed", "fetch_models", "enrich")),
        (("models",), ("make_seed", "fetch_models", "enrich", "discover_parameters")),
    ],
)
def test_sync_rebuilds_derivations_from_current_provider_data(monkeypatch, tmp_path: Path, components, tasks):
    monkeypatch.setattr(
        catalog_runner,
        "run_catalog_task",
        lambda task, *arguments: CatalogTaskResult(returncode=0, stdout=task.value, stderr=""),
    )
    monkeypatch.setattr(catalog_runner, "write_taxonomy", lambda root: (1, 2, False))

    steps = sync_catalog(tmp_path, ("stub",), components)

    assert tuple(step.detail for step in steps[:-2]) == tasks
    assert [(step.component, step.status, step.detail) for step in steps[-2:]] == [
        ("taxonomy", "completed", "1 providers, 2 models; current"),
        ("validation", "completed", "validate"),
    ]
