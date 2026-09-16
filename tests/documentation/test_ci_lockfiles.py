from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = {path.name: yaml.safe_load(path.read_text()) for path in (ROOT / ".github/workflows").glob("*.yml")}
LOCK_COMMANDS = [
    (f"{name}/{job_name}", shlex.split(step["run"]))
    for name, workflow in WORKFLOWS.items()
    for job_name, job in workflow["jobs"].items()
    for step in job.get("steps", [])
    if step.get("run", "").startswith(("uv sync ", "uv export "))
]


@pytest.mark.parametrize("stale", [False, True], ids=["fresh", "stale"])
@pytest.mark.parametrize(("name", "command"), LOCK_COMMANDS, ids=[name for name, _ in LOCK_COMMANDS])
def test_workspace_preparation_preserves_lock_and_rejects_stale_manifest(name, command, stale, tmp_path):
    uv = shutil.which("uv")
    assert uv is not None
    manifest = '[project]\nname = "ci-lockfile-probe"\nversion = "0.1.0"\nrequires-python = ">=3.13"\n'
    project = tmp_path / "pyproject.toml"
    project.write_text(manifest)
    subprocess.run(  # noqa: S603 controlled uv command in a disposable project
        [uv, "lock", "--offline", "--python", sys.executable], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    lock = tmp_path / "uv.lock"
    original = lock.read_bytes()
    if stale:
        project.write_text(manifest + "dependencies = [\"ci-lockfile-probe-dependency; sys_platform == 'never'\"]\n")
    result = subprocess.run(  # noqa: S603 workflow preparation command in a disposable project
        [uv, *command[1:], "--offline", "--python", sys.executable], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert (result.returncode != 0) == stale, result.stderr
    if stale:
        assert "lockfile" in result.stderr.lower(), result.stderr
    assert lock.read_bytes() == original


def test_prepared_workspace_commands_cannot_relock():
    for workflow in WORKFLOWS.values():
        for job in workflow["jobs"].values():
            steps = job.get("steps", [])
            expected = "--no-sync" if any(step.get("run", "").startswith("uv sync ") for step in steps) else "--locked"
            for step in steps:
                for line in step.get("run", "").splitlines():
                    if line.strip().startswith("uv run "):
                        command = shlex.split(line.rstrip("\\"))
                        if "--no-project" not in command:
                            assert expected in command
    job = WORKFLOWS["ci.yml"]["jobs"]["backend"]
    assert job["env"]["UV_NO_SYNC"] == "true"
    for script in ("export-openapi.sh", "generate-api-models.sh", "export-completion-schemas.sh"):
        for line in (ROOT / "scripts" / script).read_text().splitlines():
            if line.startswith("uv run "):
                assert "--locked" in shlex.split(line.rstrip("\\"))


def test_python_jobs_check_lock_drift_without_constraining_release_resolution():
    for workflow in WORKFLOWS.values():
        assert "UV_NO_SYNC" not in workflow.get("env", {})
        assert "UV_LOCKED" not in workflow.get("env", {})
        for job in workflow["jobs"].values():
            steps = job.get("steps", [])
            if any(step.get("run", "").startswith(("uv sync ", "uv export ")) for step in steps):
                assert any(step.get("run") == "git diff --exit-code -- uv.lock" and step.get("if") == "always()" for step in steps)
            for step in steps:
                if "uv tool install " in step.get("run", ""):
                    environment = {**workflow.get("env", {}), **job.get("env", {}), **step.get("env", {})}
                    assert not {"UV_NO_SYNC", "UV_LOCKED", "UV_FROZEN"}.intersection(environment)
                    assert not {"--locked", "--frozen", "--no-sync"}.intersection(shlex.split(step["run"]))
