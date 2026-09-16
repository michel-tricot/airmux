from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def installation(tmp_path):
    executable = os.environ.get("AIRMUX_INSTALL_BIN")
    if executable is None:
        pytest.fail("set AIRMUX_INSTALL_BIN to the candidate wheel executable installed by uv tool install")
    environment = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "NO_COLOR": "1"}
    assert Path(executable).is_file(), f"installed candidate executable does not exist: {executable}"
    return executable, environment


def run_cli(installation, directory, *args, check=True):
    executable, environment = installation
    return subprocess.run(  # noqa: S603 the installed executable is supplied by the packaging test job
        [executable, *args], cwd=directory, env=environment, text=True, capture_output=True, check=check, timeout=30
    )
