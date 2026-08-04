from __future__ import annotations

from typing import TYPE_CHECKING

from contract import SignedBundle

if TYPE_CHECKING:
    from pathlib import Path


def read_cached_bundle(cache_dir: Path) -> SignedBundle | None:
    path = cache_dir / "bundle.json"
    if not path.exists():
        return None
    return SignedBundle.model_validate_json(path.read_text(encoding="utf-8"))


def write_cached_bundle(cache_dir: Path, signed: SignedBundle) -> None:
    path = cache_dir / "bundle.json"
    tmp = cache_dir / "bundle.json.tmp"
    tmp.write_text(signed.model_dump_json(), encoding="utf-8")
    tmp.replace(path)
