from __future__ import annotations

import json
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def update_directories(ecosystem: str) -> set[Path]:
    configuration = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    return {
        ROOT / directory.lstrip("/")
        for update in configuration["updates"]
        if update["package-ecosystem"] == ecosystem
        for directory in update.get("directories", [update.get("directory", "/")])
    }


def test_dependabot_covers_python_manifests_and_native_lockfile():
    directories = update_directories("uv")
    assert ROOT in directories
    assert (ROOT / "uv.lock").is_file()
    workspace = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["workspace"]
    members = {directory for pattern in workspace["members"] for directory in ROOT.glob(pattern)}
    excluded = {directory for pattern in workspace["exclude"] for directory in ROOT.glob(pattern)}
    manifests = {
        manifest.parent
        for pattern in (
            "apps/*/pyproject.toml",
            "lib/*/pyproject.toml",
            "model-audit/pyproject.toml",
            "tests/*/pyproject.toml",
            "packaging/*/pyproject.toml",
        )
        for manifest in ROOT.glob(pattern)
    }

    assert manifests <= directories | (members - excluded)


def test_dependabot_covers_bun_workspace_manifests_and_native_lockfile():
    assert update_directories("bun") == {ROOT}
    assert (ROOT / "bun.lock").is_file()
    workspace = json.loads((ROOT / "package.json").read_text())["workspaces"]
    members = {directory for pattern in workspace["packages"] for directory in ROOT.glob(pattern)}
    manifests = {manifest.parent for pattern in ("apps/*/package.json", "lib/*/package.json") for manifest in ROOT.glob(pattern)}

    assert manifests <= members


def test_dependabot_excludes_only_the_local_airmux_project_from_registry_updates():
    configuration = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    sources = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["sources"]
    assert sources["airmux"] == {"workspace": True}
    for update in configuration["updates"]:
        expected = [{"dependency-name": "airmux"}] if update["package-ecosystem"] == "uv" else []
        assert update.get("ignore", []) == expected


def test_dependabot_covers_container_manifests():
    dockerfiles = [ROOT / "Dockerfile", *ROOT.glob("deploy/**/Dockerfile*")]
    compose_files = [*ROOT.glob("docker-compose*.yml"), *ROOT.glob("deploy/**/compose*.yml")]

    assert {dockerfile.parent for dockerfile in dockerfiles} <= update_directories("docker")
    assert {compose_file.parent for compose_file in compose_files} <= update_directories("docker-compose")


def test_dependabot_keeps_major_upgrades_focused_and_security_updates_coordinated():
    configuration = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text())
    assert update_directories("github-actions") == {ROOT}
    for update in configuration["updates"]:
        assert update["schedule"]["interval"] == "weekly"
        if update["package-ecosystem"] in {"uv", "bun"}:
            for group in update["groups"].values():
                if group.get("applies-to", "version-updates") == "version-updates":
                    assert set(group["update-types"]) <= {"minor", "patch"} or group["group-by"] == "dependency-name"
        if update["package-ecosystem"] == "uv":
            assert any(group.get("applies-to") == "security-updates" for group in update["groups"].values())
