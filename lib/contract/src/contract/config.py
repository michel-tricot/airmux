from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, Field, ValidationInfo


@dataclass(frozen=True)
class ConfigContext:
    base_dir: Path


def _resolve_path(path: Path, info: ValidationInfo) -> Path:
    if isinstance(info.context, ConfigContext):
        return info.context.base_dir / path
    return path


ConfigPath = Annotated[Path, AfterValidator(_resolve_path), Field(validate_default=True)]
