from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


def test_contract_has_only_validation_and_identity_dependencies():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["dependencies"] == ["pydantic>=2", "uuid-utils>=1.0,<2"]


def test_runtime_and_data_plane_keep_the_database_driver_optional():
    root = Path(__file__).parents[3]
    runtime = tomllib.loads((root / "lib/runtime/pyproject.toml").read_text(encoding="utf-8"))["project"]
    data_plane = tomllib.loads((root / "apps/data-plane/pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert "asyncpg" not in runtime["dependencies"]
    assert runtime["optional-dependencies"]["insecure-database"] == ["asyncpg"]
    assert "asyncpg" not in data_plane["dependencies"]
    assert "airmux-runtime" in data_plane["dependencies"]


def test_importing_contract_does_not_load_runtime_infrastructure():
    code = (
        "import contract, sys; forbidden = {'airmux_runtime', 'yaml', 'dotenv', 'asyncpg'}; "
        "assert not forbidden.intersection(sys.modules), forbidden.intersection(sys.modules)"
    )
    result = subprocess.run(  # noqa: S603 the interpreter and script are test-owned
        [
            sys.executable,
            "-c",
            code,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
