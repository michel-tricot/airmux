from __future__ import annotations

import json
import os
import shlex
import subprocess
import tomllib
from pathlib import Path

from tests.documentation.examples import cli_reference_commands, code_block
from tests.documentation.test_documentation import ROOT
from tests.installation.installation_support import run_cli


def test_documented_command_inventory_matches_installed_cli(installation, tmp_path):
    inventory = json.loads(run_cli(installation, tmp_path, "commands", "-f", "json").stdout)
    assert cli_reference_commands() <= {command["command"] for command in inventory}


def test_documented_portable_recipe_runs_outside_checkout(installation, tmp_path):
    executable, environment = installation
    locked = tomllib.loads((ROOT / "uv.lock").read_text())
    constraints = tmp_path / "constraints.txt"
    constraints.write_text("\n".join(f"{package['name']}=={package['version']}" for package in locked["package"] if "registry" in package["source"]))
    recipe = code_block("docs/development.mdx", "airmux-smoke-runner")
    install, recipe = recipe.split("\n", 1)
    assert install == "uv tool install --python 3.13 dist/airmux-*.whl"
    recipe = recipe.replace("/tmp/airmux-smoke-runner", shlex.quote(str(tmp_path / "runner")))  # noqa: S108 replace the documented path with an isolated test directory
    recipe = recipe.replace("/tmp/airmux-installation-tests", shlex.quote(str(tmp_path / "suite")))  # noqa: S108 replace the documented path with an isolated test directory
    recipe = recipe.replace("cd /tmp\n", f"cd {shlex.quote(str(tmp_path))}\n")
    result = subprocess.run(  # noqa: S603 execute the trusted recipe using the already installed candidate and cached dependencies
        ["/bin/bash", "-eu", "-o", "pipefail", "-c", recipe],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{Path(executable).parent}{os.pathsep}{environment['PATH']}",
            "UV_OFFLINE": "1",
            "UV_CONSTRAINT": str(constraints),
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
