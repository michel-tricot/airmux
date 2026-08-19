from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from refresh import staged_refresh


def test_failed_refresh_leaves_the_live_catalog_unchanged(tmp_path: Path, monkeypatch):
    live = tmp_path / "taxonomy"
    live.mkdir()
    catalog = live / "providers.yml"
    catalog.write_text("original\n")

    def fail(command, *, check, env):
        Path(env["AIRLLM_TAXONOMY_ROOT"], "providers.yml").write_text("partial\n")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(subprocess.CalledProcessError):
        staged_refresh(live, [["fetch_models.py"]])

    assert catalog.read_text() == "original\n"
