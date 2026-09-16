from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
RELEASE = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())


def steps(job: str) -> str:
    return "\n".join(step.get("run", "") + step.get("with", {}).get("script", "") for step in RELEASE["jobs"][job].get("steps", []))


def test_release_derives_sha_and_consumes_exact_successful_main_artifact():
    assert set(RELEASE[True]["workflow_dispatch"]["inputs"]) == {"tag"}
    prepare = steps("prepare")
    assert "refs/tags/$RELEASE_TAG^{commit}" in prepare
    assert "git merge-base --is-ancestor" in prepare
    assert "ci.yml" in prepare
    assert "security.yml" in prepare
    assert "candidate-${RELEASE_SHA}" in prepare
    assert "sha256sum --check SHA256SUMS" in prepare
    assert "./scripts/build-python-distribution.sh" not in prepare


def test_release_uses_official_publisher_with_narrow_permissions():
    jobs = RELEASE["jobs"]
    publisher = next(step for step in jobs["publish"]["steps"] if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@"))
    assert len(publisher["uses"].rsplit("@", 1)[1]) == 40
    assert jobs["publish"]["permissions"] == {"contents": "read", "id-token": "write"}
    assert jobs["announce"]["permissions"] == {"contents": "write"}
    for name, job in jobs.items():
        if name not in {"prepare", "publish", "announce"}:
            assert job.get("permissions", RELEASE["permissions"]) == {"contents": "read"}


def test_release_verifies_registry_bytes_and_gateway_before_announcement():
    assert set(RELEASE["jobs"]["announce"]["needs"]) == {"prepare", "verify-pypi"}
    verify = steps("verify-pypi")
    assert "pypi_artifacts.py" in verify
    assert "test_01_basic.py::test_ready_gateway_completes_and_records_usage" in verify
    assert RELEASE["jobs"]["live-providers"]["needs"] == "prepare"
