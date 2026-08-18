from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from contract import SignedBundle, uuid7

if TYPE_CHECKING:
    from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    # A per-writer temp name so concurrent processes sharing this dir never rename each other's file away.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def instance_id(cache_dir: Path) -> UUID:
    """A stable id for the deployment sharing this cache dir, created once and read by every process.

    Exclusive create means exactly one writer mints the id; other processes (uvicorn workers or
    separate instances on the same dir) read it back, so they all report as one logical instance.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "instance_id"
    try:
        with path.open("x", encoding="utf-8") as f:
            f.write(str(uuid7()))
    except FileExistsError:
        pass
    for _ in range(100):  # cover the sub-millisecond window between another process creating and writing the file
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return UUID(existing)
        time.sleep(0.005)
    msg = f"instance_id in {cache_dir} never became readable"
    raise RuntimeError(msg)


CACHE_FILE = "bundles.json"


class CachedBundles(BaseModel):
    model_config = ConfigDict(frozen=True)

    bundles: list[SignedBundle]


def read_cached_bundles(cache_dir: Path) -> CachedBundles | None:
    path = cache_dir / CACHE_FILE
    if not path.exists():
        return None
    return CachedBundles.model_validate_json(path.read_text(encoding="utf-8"))


def write_cached_bundles(cache_dir: Path, bundles: list[SignedBundle]) -> None:
    atomic_write_text(cache_dir / CACHE_FILE, CachedBundles(bundles=bundles).model_dump_json(indent=2))
