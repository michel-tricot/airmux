from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]
CI_JOBS = {"quality", "python-unit", "python-integration", "frontend", "package", "gateway", "full-stack", "browser", "docker"}
GATES = (("ci.yml", "required", CI_JOBS), ("security.yml", "dependency-security", {"pip-audit", "bun-audit", "dependency-review"}))


@pytest.mark.parametrize(("filename", "name", "dependencies"), GATES)
@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped", "pending", None])
def test_required_gate_rejects_every_unsuccessful_dependency(filename, name, dependencies, result):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
    gate = workflow["jobs"][name]
    assert set(gate["needs"]) == dependencies
    assert gate.get("name", name) == name
    assert gate["if"] == "always()"
    step = gate["steps"][-1]
    assert step["env"]["NEEDS"] == "${{ toJSON(needs) }}"
    needs = {dependency: {"result": result} for dependency in dependencies}
    if filename == "security.yml" and result == "skipped":
        needs["pip-audit"]["result"] = "success"
        needs["bun-audit"]["result"] = "success"
    completed = subprocess.run(
        ["/bin/bash", "-e", "-o", "pipefail"],
        input=step["run"],
        env={**os.environ, "NEEDS": json.dumps(needs)},
        capture_output=True,
        text=True,
        check=False,
    )
    expected = result == "success" or (filename == "security.yml" and result == "skipped")
    assert (completed.returncode == 0) == expected


def test_main_requires_only_stable_aggregate_checks():
    ruleset = json.loads((ROOT / ".github/policy/protect-main.json").read_text())
    rules = {rule["type"]: rule.get("parameters", {}) for rule in ruleset["rules"]}
    checks = rules["required_status_checks"]
    assert checks["strict_required_status_checks_policy"] is True
    assert {(check["context"], check["integration_id"]) for check in checks["required_status_checks"]} == {
        ("required", 15368),
        ("dependency-security", 15368),
    }


def test_dependency_review_uses_the_documented_free_tier_fallback_when_unavailable():
    workflow = yaml.safe_load((ROOT / ".github/workflows/security.yml").read_text())
    steps = workflow["jobs"]["dependency-review"]["steps"]
    support = next(step for step in steps if step.get("id") == "dependency_review_support")
    review = next(step for step in steps if str(step.get("uses", "")).startswith("actions/dependency-review-action@"))
    assert ".security_and_analysis.advanced_security.status" in support["run"]
    assert "pip-audit and bun audit are the free-tier fallback" in support["run"]
    assert review["if"] == "steps.dependency_review_support.outputs.available == 'true'"


def test_ci_runs_every_correctness_job_unconditionally_and_discovers_suites():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    assert set(workflow["jobs"]) == CI_JOBS | {"required"}
    for name in CI_JOBS:
        job = workflow["jobs"][name]
        assert "if" not in job
        assert job.get("continue-on-error", False) is False
    commands = "\n".join(step.get("run", "") for job in workflow["jobs"].values() for step in job.get("steps", []))
    assert "tests/acceptance/gateway -n auto" in commands
    assert workflow["jobs"]["gateway"]["strategy"]["matrix"]["shard"] == [0, 1, 2, 3]
    assert '--shard "${{ matrix.shard }}/4"' in commands
    assert '-m "not performance"' in commands
    assert "pytest -n 2 tests/acceptance/full_stack/scenarios" in commands
    assert "pytest tests/installation/portable" in commands
    assert "test_01_basic.py" not in commands
    assert "matrix.tests" not in commands
    assert "paths:" not in (ROOT / ".github/workflows/ci.yml").read_text()
    assert "paths-ignore:" not in (ROOT / ".github/workflows/ci.yml").read_text()


def test_workflows_separate_pr_nightly_and_release_work():
    workflows = {path.name for path in (ROOT / ".github/workflows").glob("*.yml")}
    assert workflows == {"ci.yml", "security.yml", "nightly.yml", "prepare-release.yml", "release.yml"}
    nightly = yaml.safe_load((ROOT / ".github/workflows/nightly.yml").read_text())
    prepare_release = yaml.safe_load((ROOT / ".github/workflows/prepare-release.yml").read_text())
    release = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    assert "pull_request" not in nightly[True]
    assert "pull_request" not in prepare_release[True]
    assert "pull_request" not in release[True]
    assert set(prepare_release[True]["workflow_dispatch"]["inputs"]) == {"bump"}
    assert release[True]["workflow_dispatch"] == {}
    nightly_commands = "\n".join(step.get("run", "") for job in nightly["jobs"].values() for step in job.get("steps", []))
    assert "pytest -m performance tests/acceptance/gateway" in nightly_commands


def test_package_once_graph_feeds_every_black_box_job():
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    for name in ("gateway", "full-stack", "browser", "docker"):
        assert "package" in jobs[name]["needs"]
    assert jobs["browser"]["needs"] == "package"
    package = "\n".join(step.get("run", "") for step in jobs["package"]["steps"])
    assert "uv build --wheel" in package
    assert "SHA256SUMS" in package
    assert jobs["package"]["outputs"]["artifact-id"] == "${{ steps.candidate.outputs.artifact-id }}"
