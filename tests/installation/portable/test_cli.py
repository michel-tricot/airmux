from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml
from tests.installation.installation_support import run_cli


def test_help_inventory_and_version_work_in_every_installation(installation, tmp_path):
    assert run_cli(installation, tmp_path, "--version").stdout.startswith("airmux ")
    inventory = json.loads(run_cli(installation, tmp_path, "commands", "-f", "json").stdout)
    assert inventory
    assert "gateway" in run_cli(installation, tmp_path, "--help").stdout
    for group in ("gateway", "control-plane"):
        help_text = run_cli(installation, tmp_path, group, "serve", "--help").stdout
        assert "--config" in help_text
        assert "--port" in help_text


def test_installed_gateway_initializes_with_the_shipped_taxonomy(installation, tmp_path):
    result = run_cli(installation, tmp_path, "gateway", "init")
    assert "taxonomy.yml" in result.stdout
    directory = tmp_path / ".airmux"
    taxonomy = yaml.safe_load((directory / "taxonomy.yml").read_text(encoding="utf-8"))
    assert taxonomy["providers"]
    assert taxonomy["models"]
    assert yaml.safe_load((directory / "bundle.yml").read_text(encoding="utf-8"))["taxonomy"] == "taxonomy.yml"
    assert run_cli(installation, tmp_path, "gateway", "validate").returncode == 0


def test_internal_modules_are_bundled_in_one_distribution(installation, tmp_path):
    executable, environment = installation
    python = Path(executable).read_text(encoding="utf-8").splitlines()[0].removeprefix("#!")
    result = subprocess.run(  # noqa: S603 isolated tool interpreter built by the packaging test job
        [
            python,
            "-I",
            "-c",
            """
import sys
from pathlib import Path
from importlib.metadata import PackageNotFoundError, distribution

if len(sys.argv) > 1:
    assert sys.version.startswith(sys.argv[1] + "."), sys.version

airmux = distribution("airmux")
for name in ("airmux-api-models", "airmux-contract", "airmux-control-plane", "airmux-data-plane", "airmux-runtime"):
    try:
        distribution(name)
    except PackageNotFoundError:
        pass
    else:
        raise AssertionError(f"unexpected internal distribution: {name}")

import api_models
import airmux_runtime
import cli
import contract
import control_plane
import data_plane
from data_plane.heartbeat import VERSION

assert VERSION == airmux.version
for module in (airmux_runtime, api_models, cli, contract, control_plane, data_plane):
    assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), module.__file__
""",
            *([os.environ["AIRMUX_INSTALL_PYTHON"]] if "AIRMUX_INSTALL_PYTHON" in os.environ else []),
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
