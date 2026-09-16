from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

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
