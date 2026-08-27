from __future__ import annotations

import tomllib
from pathlib import Path


def test_runtime_image_drops_root_privileges():
    dockerfile = Path(__file__).resolve().parents[3] / "Dockerfile"
    assert "USER 10001:10001" in dockerfile.read_text(encoding="utf-8")


def test_runtime_image_installs_backend_dependency_group():
    root = Path(__file__).resolve().parents[3]
    dockerfile = root / "Dockerfile"
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    content = dockerfile.read_text(encoding="utf-8")
    assert set(project["dependency-groups"]["backend"]) == {"cli", "control-plane", "data-plane"}
    assert content.count("uv sync --only-group backend --frozen") == 2
    assert "--no-install-package" not in content
