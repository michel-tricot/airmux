from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement


def dependency_names(dependencies: list[str]) -> set[str]:
    return {Requirement(dependency).name for dependency in dependencies}


def test_contract_has_only_validation_and_identity_dependencies():
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert dependency_names(project["dependencies"]) == {"pydantic", "uuid-utils"}


def test_runtime_and_data_plane_keep_the_database_driver_optional():
    root = Path(__file__).parents[3]
    runtime = tomllib.loads((root / "lib/runtime/pyproject.toml").read_text(encoding="utf-8"))["project"]
    data_plane = tomllib.loads((root / "apps/data-plane/pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert "asyncpg" not in dependency_names(runtime["dependencies"])
    assert dependency_names(runtime["optional-dependencies"]["insecure-database"]) == {"asyncpg"}
    assert "asyncpg" not in dependency_names(data_plane["dependencies"])
    assert "airmux-runtime" in dependency_names(data_plane["dependencies"])


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
