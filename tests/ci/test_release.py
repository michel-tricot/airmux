from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
PREPARE_RELEASE = yaml.safe_load((ROOT / ".github/workflows/prepare-release.yml").read_text())
RELEASE = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())


def steps(job: str) -> str:
    return "\n".join(step.get("run", "") + step.get("with", {}).get("script", "") for step in RELEASE["jobs"][job].get("steps", []))


def test_release_branch_changes_only_the_public_version():
    bump = PREPARE_RELEASE[True]["workflow_dispatch"]["inputs"]["bump"]
    assert bump["options"] == ["patch", "minor", "major"]
    commands = "\n".join(step.get("run", "") for step in PREPARE_RELEASE["jobs"]["release-branch"]["steps"])
    assert 'version_file = Path("VERSION")' in commands
    assert 'test "$(git diff --name-only)" = "VERSION"' in commands
    assert "refs/heads/$RELEASE_BRANCH" in commands
    assert "compare/main...$RELEASE_BRANCH?expand=1" in commands


def test_release_is_manual_and_requires_complete_checks_on_the_exact_main_commit():
    dispatch = RELEASE[True]["workflow_dispatch"]
    assert set(dispatch["inputs"]) == {"commit"}
    assert dispatch["inputs"]["commit"]["required"] is True
    assert dispatch["inputs"]["commit"]["type"] == "string"
    source = next(step for step in RELEASE["jobs"]["prepare"]["steps"] if step.get("id") == "source")
    assert source["env"]["RELEASE_SHA"] == "${{ inputs.commit }}"
    prepare = steps("prepare")
    assert 'git merge-base --is-ancestor "$RELEASE_SHA" "$GITHUB_SHA"' in prepare
    assert 'git diff --quiet "$RELEASE_SHA^" "$RELEASE_SHA" -- VERSION' in prepare
    assert 'version="$(git show "$RELEASE_SHA:VERSION")"' in prepare
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in prepare
    assert "main-ci.yml" in prepare
    assert "Main CI required" in prepare
    assert "security.yml" in prepare
    assert "head_sha: process.env.RELEASE_SHA" in prepare
    assert "run.conclusion === 'success'" in prepare
    assert "job.name === check" in prepare
    assert "setTimeout" not in prepare
    assert RELEASE["jobs"]["prepare"]["outputs"]["ci-run-id"] == "${{ steps.checks.outputs.ci-run-id }}"


def test_release_consumes_main_ci_artifacts_without_copying_them():
    assert not any(step.get("uses", "").startswith("actions/upload-artifact@") for step in RELEASE["jobs"]["prepare"]["steps"])
    for name in ("installation", "live-providers"):
        assert any(step.get("uses") == "./.github/actions/install-candidate" for step in RELEASE["jobs"][name]["steps"])
    for name in ("installation", "live-providers", "publish", "verify-pypi"):
        downloads = [step for step in RELEASE["jobs"][name]["steps"] if step.get("uses", "").startswith("actions/download-artifact@")]
        assert downloads
        for download in downloads:
            assert download["with"]["run-id"] == "${{ needs.prepare.outputs.ci-run-id }}"
            assert download["with"]["github-token"] == "${{ github.token }}"
    assert "container-${{ needs.prepare.outputs.sha }}" in str(RELEASE["jobs"]["publish"]["steps"])
    assert "sha256sum --check SHA256SUMS" in steps("publish")


def test_release_checks_candidate_before_tag_and_registry_before_announcement():
    jobs = RELEASE["jobs"]
    assert set(jobs["tag"]["needs"]) == {"prepare", "installation", "live-providers"}
    assert jobs["publish"]["needs"] == ["prepare", "tag"]
    assert set(jobs["announce"]["needs"]) == {"prepare", "verify-pypi", "verify-container"}
    assert "pypi_artifacts.py" in steps("verify-pypi")
    assert "test_ready_gateway_completes_and_records_usage" in steps("verify-pypi")
    assert "docker pull" in steps("verify-container")
    assert "refs/tags/$RELEASE_TAG" in steps("tag")
    assert jobs["publish"]["permissions"] == {"contents": "read", "actions": "read", "id-token": "write", "packages": "write"}
