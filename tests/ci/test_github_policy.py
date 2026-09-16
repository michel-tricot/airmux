from __future__ import annotations

import os
import runpy
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).parents[2]


def test_launcher_uses_project_environment():
    uv = shutil.which("uv")
    assert uv is not None
    environment = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"} | {
        "PATH": os.pathsep.join((str(Path(uv).parent), "/usr/bin", "/bin"))
    }

    completed = subprocess.run(  # noqa: S603 repository-owned launcher path is fixed
        [str(ROOT / "scripts/github-policy"), "--help"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "diff" in completed.stdout


def test_github_api_receives_json_body(tmp_path, monkeypatch):
    executable = tmp_path / "gh"
    executable.write_text('#!/bin/sh\ncase " $* " in *" --input - "*) cat;; *) exit 2;; esac\n')
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join((str(tmp_path), os.environ["PATH"])))
    module = runpy.run_path(str(ROOT / "scripts/github-policy"))
    gh = cast("Callable[[str, str, str, object | None], object | None]", module["gh"])

    assert gh("michel-tricot/airmux", "PUT", "actions/permissions", {"enabled": True}) == {"enabled": True}
