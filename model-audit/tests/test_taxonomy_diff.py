from __future__ import annotations

import json
from typing import TYPE_CHECKING

from model_audit.taxonomy_diff import compare_taxonomies, summarize_taxonomy_diff

if TYPE_CHECKING:
    from pathlib import Path


def write_taxonomy(root: Path, model: dict[str, object]) -> None:
    (root / "models").mkdir(parents=True)
    (root / "schemas").mkdir()
    (root / "icons").mkdir()
    (root / "providers.yml").write_text("providers:\n- id: example\n  name: Example\n", encoding="utf-8")
    (root / "models" / "example.json").write_text(json.dumps({"models": [model]}), encoding="utf-8")
    (root / "taxonomy.yml").write_text("models: []\n", encoding="utf-8")


def test_taxonomy_diff_reports_exact_model_fields_and_summary(tmp_path: Path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    write_taxonomy(before, {"id": "model", "context_length": 10})
    write_taxonomy(after, {"id": "model", "context_length": 20, "pricing": {"input_per_mtok": 1.0}})

    rows = compare_taxonomies(before, after)

    assert {(row["field"], row["before"], str(row["after"])) for row in rows} == {
        ("context_length", 10, "20"),
        ("pricing", None, "{'input_per_mtok': '1.0'}"),
    }
    assert summarize_taxonomy_diff(rows) == [{"scope": "catalog-model", "change": "changed", "count": 2}]
