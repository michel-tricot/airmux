from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
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
    assert source["env"]["SOURCE_SHA"] == "${{ inputs.commit }}"
    prepare = steps("prepare")
    assert "main-ci.yml" in prepare
    assert "Main CI required" in prepare
    assert "security.yml" in prepare
    assert "head_sha: process.env.SOURCE_SHA" in prepare
    assert "run.conclusion === 'success'" in prepare
    assert "job.name === check" in prepare
    assert "setTimeout" not in prepare
    assert RELEASE["jobs"]["prepare"]["outputs"]["ci-run-id"] == "${{ steps.checks.outputs.ci-run-id }}"


def git(repository, *args):
    return subprocess.run(  # noqa: S603 controlled Git commands in a temporary test repository
        ["/usr/bin/git", "-C", str(repository), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def release_repository(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Release test")
    git(tmp_path, "config", "user.email", "release@example.test")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "tag.gpgsign", "false")
    for name, version in (("initial", "0.2.5"), ("version", "0.2.6"), ("fix", "0.2.6"), ("latest", "0.2.7")):
        (tmp_path / "VERSION").write_text(version + "\n")
        git(tmp_path, "add", "VERSION")
        git(tmp_path, "commit", "-qm", name, "--allow-empty")
        git(tmp_path, "tag", name)
    git(tmp_path, "checkout", "-qb", "unmerged", "version")
    git(tmp_path, "commit", "-qm", "unmerged fix", "--allow-empty")
    git(tmp_path, "checkout", "-q", "--detach", "latest")
    return tmp_path


def validate_source(repository, source_sha, event_name="workflow_dispatch"):
    source = next(step for step in RELEASE["jobs"]["prepare"]["steps"] if step.get("id") == "source")
    return subprocess.run(
        ["/bin/bash", "-e", "-o", "pipefail"],
        input=source["run"],
        cwd=repository,
        env={
            **os.environ,
            "SOURCE_SHA": source_sha,
            "GITHUB_EVENT_NAME": event_name,
            "GITHUB_SHA": git(repository, "rev-parse", "HEAD"),
            "GITHUB_OUTPUT": str(repository / "output"),
            "GITHUB_STEP_SUMMARY": str(repository / "summary"),
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("source", ["version", "fix"])
def test_release_pins_the_requested_commit_after_main_advances(release_repository, source):
    source_sha = git(release_repository, "rev-parse", source)
    completed = validate_source(release_repository, source_sha)
    assert completed.returncode == 0, completed.stderr
    assert (release_repository / "output").read_text().splitlines() == [f"sha={source_sha}", "version=0.2.6", "tag=v0.2.6"]


@pytest.mark.parametrize("source", ["HEAD", "0" * 40, "unmerged"])
def test_release_rejects_invalid_or_unmerged_commits(release_repository, source):
    source_sha = git(release_repository, "rev-parse", source) if source == "unmerged" else source
    assert validate_source(release_repository, source_sha).returncode != 0
    assert not (release_repository / "output").exists()


@pytest.mark.parametrize("version", ["invalid", None])
def test_release_rejects_invalid_or_missing_version(release_repository, version):
    version_file = release_repository / "VERSION"
    if version is None:
        version_file.unlink()
    else:
        version_file.write_text(version)
    git(release_repository, "commit", "-qam", "invalid version")
    source_sha = git(release_repository, "rev-parse", "HEAD")
    assert validate_source(release_repository, source_sha).returncode != 0
    assert not (release_repository / "output").exists()


def test_release_rejects_an_existing_version_tag(release_repository):
    git(release_repository, "tag", "v0.2.6", "version")
    source_sha = git(release_repository, "rev-parse", "fix")
    assert validate_source(release_repository, source_sha).returncode != 0
    assert not (release_repository / "output").exists()


def test_manual_release_keeps_requested_sha_when_ci_event_is_push(release_repository, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    source_sha = git(release_repository, "rev-parse", "fix")
    completed = validate_source(release_repository, source_sha)
    assert completed.returncode == 0, completed.stderr
    assert (release_repository / "output").read_text().splitlines() == [f"sha={source_sha}", "version=0.2.6", "tag=v0.2.6"]


def test_automatic_release_uses_push_commit(release_repository):
    source_sha = git(release_repository, "rev-parse", "HEAD")
    completed = validate_source(release_repository, "0" * 40, event_name="push")
    assert completed.returncode == 0, completed.stderr
    assert (release_repository / "output").read_text().splitlines() == [f"sha={source_sha}", "version=0.2.7", "tag=v0.2.7"]


def test_automatic_release_requires_version_only_commit(release_repository):
    (release_repository / "README.md").write_text("Other changes\n")
    git(release_repository, "add", "README.md")
    git(release_repository, "commit", "-qm", "Other changes")
    assert validate_source(release_repository, "0" * 40, event_name="push").returncode != 0
    assert not (release_repository / "output").exists()


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
    assert "container-${{ needs.prepare.outputs.sha }}" in str(jobs["installation"]["steps"])
    assert 'docker run --rm --entrypoint airmux "$image" --version' in steps("installation")
    assert "org.opencontainers.image.revision" in steps("installation")
    assert jobs["publish"]["needs"] == ["prepare", "tag"]
    assert set(jobs["announce"]["needs"]) == {"prepare", "publish", "verify-pypi", "verify-container"}
    for name in ("installation", "verify-container"):
        assert jobs[name]["runs-on"] == "${{ matrix.runner }}"
        assert jobs[name]["strategy"]["fail-fast"] is False
        assert jobs[name]["strategy"]["matrix"]["include"] == [
            {"arch": "amd64", "runner": "ubuntu-24.04"},
            {"arch": "arm64", "runner": "ubuntu-24.04-arm"},
        ]
        assert jobs[name]["env"]["ARCH"] == "${{ matrix.arch }}"
        assert "{{.Os}}/{{.Architecture}}" in steps(name)
        assert 'sort == ["linux/amd64", "linux/arm64"]' in steps(name)
    assert 'test "$digest" = "${candidate##*@}"' in steps("publish")
    announcement = next(step for step in jobs["announce"]["steps"] if step.get("name") == "Publish the verified GitHub release")
    assert announcement["env"]["IMAGE"] == "${{ needs.publish.outputs.image }}"
    assert "outputs" not in jobs["verify-container"]
    assert "pypi_artifacts.py" in steps("verify-pypi")
    assert "test_ready_gateway_completes_and_records_usage" in steps("verify-pypi")
    assert "docker pull" in steps("verify-container")
    assert "refs/tags/$RELEASE_TAG" in steps("tag")
    assert jobs["publish"]["permissions"] == {"contents": "read", "actions": "read", "id-token": "write", "packages": "write"}
    announce = steps("announce")
    assert 'os.environ["IMAGE"]' in announce
    assert "compose.replace(local_image, release_image)" in announce
    assert 'gh release create "$RELEASE_TAG" "$RUNNER_TEMP/docker-compose.yml"' in announce
