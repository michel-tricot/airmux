from __future__ import annotations

import json
import shutil
import subprocess
import sys

from tests.documentation.examples import cli_reference_commands
from tests.documentation.test_documentation import ROOT
from tests.installation.installation_support import run_cli


def test_documented_command_inventory_matches_installed_cli(installation, tmp_path):
    inventory = json.loads(run_cli(installation, tmp_path, "commands", "-f", "json").stdout)
    assert cli_reference_commands() <= {command["command"] for command in inventory}


def test_candidate_runs_outside_checkout(installation, tmp_path):
    executable, environment = installation
    portable = tmp_path / "tests" / "installation" / "portable"
    portable.mkdir(parents=True)
    for path in (ROOT / "tests/installation/portable").glob("*.py"):
        shutil.copy2(path, portable / path.name)
    shutil.copy2(ROOT / "tests/installation/installation_support.py", portable.parent / "installation_support.py")
    acceptance = tmp_path / "tests" / "acceptance"
    acceptance.mkdir()
    shutil.copy2(ROOT / "tests/acceptance/process_harness.py", acceptance / "process_harness.py")
    result = subprocess.run(
        [sys.executable, "-I", "-m", "pytest", "-o", "pythonpath=.", "tests/installation/portable"],
        cwd=tmp_path,
        env={
            **environment,
            "AIRMUX_INSTALL_BIN": executable,
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
