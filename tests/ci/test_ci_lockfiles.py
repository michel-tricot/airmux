from __future__ import annotations

import shlex
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_workspace_preparation_is_frozen_and_lock_drift_is_checked_once():
    workflows = [yaml.safe_load(path.read_text()) for path in (ROOT / ".github/workflows").glob("*.yml")]
    actions = [yaml.safe_load(path.read_text()) for path in (ROOT / ".github/actions").glob("*/action.yml")]
    drift_checks = []
    step_groups = [job.get("steps", []) for workflow in workflows for job in workflow["jobs"].values()]
    step_groups.extend(action["runs"]["steps"] for action in actions)
    for steps in step_groups:
        for step in steps:
            run = step.get("run", "")
            for line in run.splitlines():
                if not line.strip().startswith(("uv sync ", "bun install ")):
                    continue
                command = shlex.split(line.rstrip("\\"))
                if command[:2] == ["uv", "sync"]:
                    assert "--locked" in command
                if command[:2] == ["bun", "install"]:
                    assert "--frozen-lockfile" in command
            if run == "git diff --exit-code -- uv.lock bun.lock":
                drift_checks.append(step)
    assert len(drift_checks) == 1
