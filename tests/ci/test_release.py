from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
PREPARE_RELEASE = yaml.safe_load((ROOT / ".github/workflows/prepare-release.yml").read_text())
RELEASE = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())


def steps(job: str) -> str:
    return "\n".join(step.get("run", "") + step.get("with", {}).get("script", "") for step in RELEASE["jobs"][job].get("steps", []))


def prepare_steps() -> str:
    return "\n".join(step.get("run", "") for step in PREPARE_RELEASE["jobs"]["release-branch"]["steps"])


def test_release_branch_bumps_only_the_root_version_and_links_to_a_pull_request():
    bump = PREPARE_RELEASE[True]["workflow_dispatch"]["inputs"]["bump"]
    assert bump["type"] == "choice"
    assert bump["options"] == ["patch", "minor", "major"]
    commands = prepare_steps()
    assert 'version_file = Path("VERSION")' in commands
    assert 'test "$(git diff --name-only)" = "VERSION"' in commands
    assert 'test -z "$(git ls-files --others --exclude-standard)"' in commands
    assert "refs/heads/$RELEASE_BRANCH" in commands
    assert "compare/main...$RELEASE_BRANCH?expand=1" in commands
    assert "gh pr create" not in commands
    assert "gh workflow run" not in commands


def test_release_derives_sha_and_consumes_exact_successful_main_artifact():
    assert RELEASE[True]["workflow_dispatch"] == {}
    assert RELEASE[True]["push"] == {"branches": ["main"], "paths": ["VERSION"]}
    prepare = steps("prepare")
    assert 'RELEASE_SHA="$GITHUB_SHA"' in prepare
    assert 'RELEASE_TAG="v$version"' in prepare
    assert 'version="$(cat VERSION)"' in prepare
    assert "ci.yml" in prepare
    assert "security.yml" in prepare
    assert "candidate-${RELEASE_SHA}" in prepare
    assert "sha256sum --check SHA256SUMS" in prepare
    assert "./scripts/build-python-distribution.sh" not in prepare


def test_release_uses_official_publisher_with_narrow_permissions():
    jobs = RELEASE["jobs"]
    publisher = next(step for step in jobs["publish"]["steps"] if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@"))
    assert len(publisher["uses"].rsplit("@", 1)[1]) == 40
    assert jobs["publish"]["permissions"] == {"contents": "read", "id-token": "write", "packages": "write"}
    assert jobs["announce"]["permissions"] == {"contents": "write"}
    for name, job in jobs.items():
        if name not in {"prepare", "publish", "verify-container", "announce"}:
            assert job.get("permissions", RELEASE["permissions"]) == {"contents": "read"}


def test_release_verifies_registry_bytes_and_gateway_before_announcement():
    assert set(RELEASE["jobs"]["announce"]["needs"]) == {"prepare", "verify-pypi", "verify-container"}
    verify = steps("verify-pypi")
    assert "pypi_artifacts.py" in verify
    assert "test_01_basic.py::test_ready_gateway_completes_and_records_usage" in verify
    assert RELEASE["jobs"]["live-providers"]["needs"] == "prepare"


def test_release_publishes_the_exact_ci_container_candidate():
    prepare = steps("prepare")
    publish = steps("publish")
    verify = steps("verify-container")

    assert "container-${RELEASE_SHA}" in prepare
    assert "sha256sum --check SHA256SUMS" in prepare
    assert "docker load" not in publish
    image_step = next(step for step in RELEASE["jobs"]["publish"]["steps"] if step.get("id") == "image")
    assert image_step["env"]["IMAGE"] == "ghcr.io/michel-tricot/airmux"
    assert "docker buildx imagetools create" in publish
    assert "docker pull" in verify
    assert "--entrypoint airmux" in verify
    assert "Container: $IMAGE" in steps("announce")


def test_release_creates_the_immutable_tag_after_candidate_checks():
    tag = RELEASE["jobs"]["tag"]
    tag_step = next(step for step in tag["steps"] if step.get("name") == "Create the protected release tag")
    assert set(tag["needs"]) == {"prepare", "installation", "live-providers"}
    assert tag_step["env"]["GH_TOKEN"] == "${{ secrets.RELEASE_GITHUB_TOKEN }}"
    assert 'test -n "$GH_TOKEN"' in tag_step["run"]
    assert "refs/tags/$RELEASE_TAG" in steps("tag")
    assert RELEASE["jobs"]["publish"]["needs"] == ["prepare", "tag"]
