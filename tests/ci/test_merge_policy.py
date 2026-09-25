from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]
FAST_JOBS = {"quality", "python-unit", "python-integration", "frontend", "package"}
MAIN_JOBS = FAST_JOBS | {"gateway", "full-stack", "browser", "docker"}


@pytest.mark.parametrize(("filename", "expected"), [("ci.yml", FAST_JOBS), ("main-ci.yml", MAIN_JOBS)])
@pytest.mark.parametrize("failure", ["failure", "cancelled", "skipped"])
def test_required_gate_rejects_unsuccessful_jobs(filename, expected, failure):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
    gate = workflow["jobs"]["required"]
    assert set(gate["needs"]) == expected
    assert gate["if"] == "always()"
    for failed_job in expected:
        needs = {name: {"result": "success"} for name in expected}
        needs[failed_job] = {"result": failure}
        completed = subprocess.run(
            ["/bin/bash", "-e", "-o", "pipefail"],
            input=gate["steps"][-1]["run"],
            env={**os.environ, "NEEDS": json.dumps(needs)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode != 0, failed_job


@pytest.mark.parametrize(("filename", "expected"), [("ci.yml", FAST_JOBS), ("main-ci.yml", MAIN_JOBS)])
def test_required_gate_accepts_all_successful_jobs(filename, expected):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
    needs = {name: {"result": "success"} for name in expected}
    completed = subprocess.run(
        ["/bin/bash", "-e", "-o", "pipefail"],
        input=workflow["jobs"]["required"]["steps"][-1]["run"],
        env={**os.environ, "NEEDS": json.dumps(needs)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0


def test_ci_events_and_candidate_coverage():
    pull_request = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    main = yaml.safe_load((ROOT / ".github/workflows/main-ci.yml").read_text())
    assert set(pull_request["jobs"]) == FAST_JOBS | {"required"}
    assert set(main["jobs"]) == MAIN_JOBS | {"required"}
    assert set(pull_request[True]) == {"pull_request"}
    assert set(main[True]) == {"push", "workflow_dispatch"}
    assert main[True]["push"] == {"branches": ["main"]}
    assert pull_request["name"] == "PR CI"
    assert main["name"] == "Main CI"
    assert main["jobs"]["required"]["name"] == "Main CI required"
    for name in ("gateway", "full-stack", "browser", "docker"):
        assert "package" in main["jobs"][name]["needs"]
    assert main["jobs"]["package"]["outputs"]["artifact-id"] == "${{ steps.candidate.outputs.artifact-id }}"


def test_branch_protection_uses_pr_and_security_gates():
    ruleset = json.loads((ROOT / ".github/policy/protect-main.json").read_text())
    checks = next(rule["parameters"] for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
    assert {(check["context"], check["integration_id"]) for check in checks["required_status_checks"]} == {
        ("required", 15368),
        ("dependency-security", 15368),
    }


@pytest.mark.parametrize(("audit", "expected"), [(None, True), ("pip-audit", False), ("bun-audit", False)])
def test_security_gate_requires_both_audits(audit, expected):
    workflow = yaml.safe_load((ROOT / ".github/workflows/security.yml").read_text())
    assert set(workflow["jobs"]) == {"pip-audit", "bun-audit", "dependency-security"}
    gate = workflow["jobs"]["dependency-security"]
    assert set(gate["needs"]) == {"pip-audit", "bun-audit"}
    assert gate["if"] == "always()"
    needs = {name: {"result": "success"} for name in ("pip-audit", "bun-audit")}
    if audit is not None:
        needs[audit] = {"result": "failure"}
    completed = subprocess.run(
        ["/bin/bash", "-e", "-o", "pipefail"],
        input=gate["steps"][-1]["run"],
        env={**os.environ, "NEEDS": json.dumps(needs)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (completed.returncode == 0) == expected


def test_nightly_extended_checks_are_manual_and_cold_docker_is_removed():
    workflow = yaml.safe_load((ROOT / ".github/workflows/nightly.yml").read_text())
    assert "cold-docker" not in workflow["jobs"]
    for name in ("performance", "performance-scaling", "soak"):
        assert workflow["jobs"][name]["if"] == "github.event_name == 'workflow_dispatch'"
    for name in ("compatibility", "live-providers"):
        assert "if" not in workflow["jobs"][name]


def test_workflow_display_names_are_title_case():
    expected = {
        "ci.yml": "PR CI",
        "main-ci.yml": "Main CI",
        "security.yml": "Security",
        "nightly.yml": "Nightly",
        "prepare-release.yml": "Prepare Release",
        "release.yml": "Publish Release",
    }
    actual = {path.name: yaml.safe_load(path.read_text())["name"] for path in (ROOT / ".github/workflows").glob("*.yml")}
    assert actual == expected
