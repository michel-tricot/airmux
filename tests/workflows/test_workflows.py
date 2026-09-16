from __future__ import annotations

import os
import re
import shutil
import subprocess
from functools import cache
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).parents[2]
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.y*ml"))
ACTIONS = sorted((ROOT / ".github/actions").glob("*/action.y*ml"))


@cache
def action_inputs(uses: str) -> frozenset[str]:
    action, revision = uses.split("@")
    assert re.fullmatch(r"[0-9a-f]{40}", revision), uses
    owner, repository, *directories = action.split("/")
    for filename in ("action.yml", "action.yaml"):
        path = "/".join([*directories, filename])
        response = httpx.get(f"https://raw.githubusercontent.com/{owner}/{repository}/{revision}/{path}", timeout=10)
        if response.status_code == 404 and filename == "action.yml":
            continue
        response.raise_for_status()
        return frozenset(name.lower() for name in yaml.safe_load(response.text).get("inputs", {}))
    raise AssertionError(uses)


@pytest.mark.skipif(os.environ.get("AIRMUX_VALIDATE_ACTION_INPUTS") != "1", reason="Enable upstream action metadata checks explicitly")
@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_action_inputs_match_pinned_metadata(path):
    workflow = yaml.safe_load(path.read_text())
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step and not step["uses"].startswith("./"):
                unknown = frozenset(name.lower() for name in step.get("with", {})) - action_inputs(step["uses"])
                assert not unknown, f"{path.name}: {step['uses']}: unknown inputs {sorted(unknown)}"


@pytest.mark.skipif(os.environ.get("AIRMUX_VALIDATE_ACTION_INPUTS") != "1", reason="Enable upstream action metadata checks explicitly")
def test_pinned_action_metadata_rejects_unknown_input(tmp_path):
    workflow = tmp_path / "invalid.yml"
    workflow.write_text(
        "jobs:\n  check:\n    steps:\n"
        "      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1\n"
        "        with:\n          missing-input: true\n"
    )
    with pytest.raises(AssertionError, match=r"unknown inputs.*missing-input"):
        test_action_inputs_match_pinned_metadata(workflow)


@pytest.mark.skipif(os.environ.get("AIRMUX_VALIDATE_ACTION_INPUTS") != "1", reason="Enable upstream action metadata checks explicitly")
@pytest.mark.parametrize("path", ACTIONS, ids=lambda path: str(path.parent.relative_to(ROOT)))
def test_composite_action_inputs_match_pinned_metadata(path):
    action = yaml.safe_load(path.read_text())
    for step in action["runs"]["steps"]:
        if "uses" in step and not step["uses"].startswith("./"):
            unknown = frozenset(name.lower() for name in step.get("with", {})) - action_inputs(step["uses"])
            assert not unknown, f"{path}: {step['uses']}: unknown inputs {sorted(unknown)}"


@pytest.mark.parametrize("path", ACTIONS, ids=lambda path: str(path.parent.relative_to(ROOT)))
def test_composite_actions_pin_external_dependencies(path):
    action = yaml.safe_load(path.read_text())
    for step in action["runs"]["steps"]:
        if "uses" in step and not step["uses"].startswith("./"):
            _, revision = step["uses"].split("@")
            assert re.fullmatch(r"[0-9a-f]{40}", revision), step["uses"]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda path: path.name)
def test_workflow_security_boundaries(path):
    workflow = yaml.safe_load(path.read_text())
    assert workflow["permissions"] == {"contents": "read"}
    for name, job in workflow["jobs"].items():
        permissions = job.get("permissions", workflow["permissions"])
        expected_permissions = {
            "prepare": {"contents": "read", "actions": "read"},
            "release-branch": {"contents": "write"},
            "publish": {"contents": "read", "id-token": "write"},
            "announce": {"contents": "write"},
        }.get(name, {"contents": "read"})
        assert permissions == expected_permissions
        assert "uses" not in job
        assert 0 < job["timeout-minutes"] <= 30
        for step in job["steps"]:
            if "uses" not in step:
                continue
            if step["uses"].startswith("./"):
                assert (ROOT / step["uses"] / "action.yml").is_file()
                continue
            action, revision = step["uses"].split("@")
            assert re.fullmatch(r"[0-9a-f]{40}", revision), step["uses"]
            if action == "actions/checkout":
                assert step["with"]["persist-credentials"] is False


@pytest.mark.parametrize(
    ("step", "diagnostic"),
    [
        ("run: echo ${{ github.missing_property }}", 'property "missing_property"'),
        ("run: [", "could not parse as YAML"),
        ("run: echo $unquoted", "shellcheck"),
    ],
)
def test_actionlint_rejects_invalid_workflows(step, diagnostic):
    actionlint = shutil.which("actionlint")
    if actionlint is None:
        pytest.skip("Install actionlint to exercise workflow diagnostics")
    workflow = f"name: invalid\non: pull_request\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - {step}\n"
    result = subprocess.run([actionlint, "-"], input=workflow, text=True, capture_output=True, check=False, timeout=10)  # noqa: S603 trusted actionlint executable resolved from PATH
    assert result.returncode != 0
    assert diagnostic in result.stdout
