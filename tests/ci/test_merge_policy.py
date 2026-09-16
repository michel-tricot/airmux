from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml
from scripts.ci_policy import Selection, required_jobs, validate_results

ROOT = Path(__file__).parents[2]
GATES = (
    ("ci.yml", "ci-correctness", {"changes", *required_jobs(Selection(), "ci")}),
    ("docker-deployments.yml", "docker-correctness", {"changes", *required_jobs(Selection(), "docker")}),
    ("dependency-security.yml", "dependency-security", {"python", "javascript"}),
)


@pytest.mark.parametrize(("filename", "name", "dependencies"), GATES)
@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped", "pending", None])
def test_required_gate_rejects_every_unsuccessful_dependency(filename, name, dependencies, result):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
    gate = workflow["jobs"][name]
    assert set(gate["needs"]) == dependencies
    assert gate.get("name", name) == name
    assert gate["if"] == "always()"
    gate_step = gate["steps"][-2] if filename != "dependency-security.yml" else gate["steps"][-1]
    assert gate_step["env"]["NEEDS"] == "${{ toJSON(needs) }}"
    for dependency in dependencies:
        needs = {name: {"result": result if name == dependency else "success", "outputs": {}} for name in dependencies}
        if filename != "dependency-security.yml":
            needs["changes"]["outputs"] = {"frontend": "true", "backend": "true", "deployment": "true"}
            scope = "ci" if filename == "ci.yml" else "docker"
            assert gate_step["run"] == f"uv run --no-sync python -m scripts.ci_policy gate {scope}"
            if result == "success":
                validate_results(json.dumps(needs), scope)
            else:
                with pytest.raises(ValueError, match=r"must succeed|results rejected|validation error"):
                    validate_results(json.dumps(needs), scope)
            continue
        completed = subprocess.run(
            ["/bin/bash", "-e", "-o", "pipefail"],
            input=gate["steps"][0]["run"],
            env={**os.environ, "NEEDS": json.dumps(needs)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert (completed.returncode == 0) == (result == "success"), (dependency, completed.stdout, completed.stderr)


@pytest.mark.parametrize(("filename", "name", "dependencies"), GATES)
def test_required_gate_rejects_empty_results(filename, name, dependencies):
    if filename != "dependency-security.yml":
        with pytest.raises(ValueError, match="changes must succeed"):
            validate_results("{}", "ci" if filename == "ci.yml" else "docker")
        return
    workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
    completed = subprocess.run(
        ["/bin/bash", "-e", "-o", "pipefail"],
        input=workflow["jobs"][name]["steps"][0]["run"],
        env={**os.environ, "NEEDS": "{}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0


def test_main_requires_current_base_checks_from_github_actions_with_admin_pull_request_bypass():
    ruleset = json.loads((ROOT / ".github/rulesets/protect-main.json").read_text())
    assert ruleset["enforcement"] == "active"
    assert ruleset["conditions"] == {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}
    assert ruleset["bypass_actors"] == [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
    rules = {rule["type"]: rule.get("parameters", {}) for rule in ruleset["rules"]}
    assert {"deletion", "non_fast_forward", "required_linear_history", "pull_request", "required_status_checks"} == set(rules)
    assert rules["pull_request"]["allowed_merge_methods"] == ["squash"]
    checks = rules["required_status_checks"]
    assert checks["strict_required_status_checks_policy"] is True
    assert checks["do_not_enforce_on_create"] is False
    assert {(check["context"], check["integration_id"]) for check in checks["required_status_checks"]} == {(name, 15368) for _, name, _ in GATES}


@pytest.mark.parametrize(("filename", "name", "dependencies"), GATES)
def test_required_workflows_run_on_every_pull_request(filename, name, dependencies):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
    triggers = workflow[True]
    assert "pull_request" in triggers
    assert triggers["pull_request"] is None
    assert triggers["push"] == {"branches": ["main"]}
    assert workflow["jobs"][name].get("continue-on-error", False) is False
    for dependency in dependencies:
        assert workflow["jobs"][dependency].get("continue-on-error", False) is False
