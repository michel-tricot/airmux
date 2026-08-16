from __future__ import annotations

from pathlib import Path


def test_runtime_image_drops_root_privileges():
    dockerfile = Path(__file__).resolve().parents[3] / "Dockerfile"
    assert "USER 10001:10001" in dockerfile.read_text(encoding="utf-8")
