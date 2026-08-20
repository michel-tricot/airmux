from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from pydantic import TypeAdapter

from provider_parity.models import Case, ExpectedDifference

if TYPE_CHECKING:
    from pathlib import Path

CASES = TypeAdapter(list[Case])
DIFFERENCES = TypeAdapter(list[ExpectedDifference])


def load_cases(path: Path) -> list[Case]:
    cases = [Case.model_validate(yaml.safe_load(case.read_text(encoding="utf-8"))) for case in sorted(path.rglob("*.yml"))]
    names = [case.id for case in cases]
    if len(names) != len(set(names)):
        duplicates = sorted(name for name in set(names) if names.count(name) > 1)
        message = f"duplicate case ids: {', '.join(duplicates)}"
        raise ValueError(message)
    return cases


def load_expected_differences(path: Path) -> list[ExpectedDifference]:
    if not path.exists():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        message = "expected differences must be a mapping"
        raise TypeError(message)
    return DIFFERENCES.validate_python(document.get("differences") or [])
