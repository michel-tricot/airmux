from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
ROLE_IMAGE_VARIABLES = ("AIRMUX_CONTROL_PLANE_IMAGE", "AIRMUX_DATA_PLANE_IMAGE", "AIRMUX_CONSOLE_IMAGE")
ROLES = {"control-plane", "data-plane", "console", "airmux"}


def test_dockerfile_builds_one_role_based_image() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    stages = re.findall(r"^FROM .+ AS ([a-z0-9-]+)$", dockerfile, re.MULTILINE)

    assert not ROLES.intersection(stages)


def test_compose_topologies_project_the_same_image_into_roles() -> None:
    compact_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    split_text = (ROOT / "docker-compose.split.yml").read_text(encoding="utf-8")
    compact = yaml.safe_load(compact_text)
    split = yaml.safe_load(split_text)

    compact_services = compact["services"]
    assert "build" not in compact_services["airmux"]
    assert compact_services["airmux"]["image"] == "${AIRMUX_IMAGE:-airmux:local}"
    assert compact_services["airmux"]["command"] == "airmux"
    for name in ("migrate", "taxonomy"):
        assert compact_services[name]["image"] == "${AIRMUX_IMAGE:-airmux:local}"
        assert compact_services[name]["entrypoint"] == ["/usr/bin/tini", "--", "airmux"]
        assert compact_services[name]["restart"] == "no"
    assert compact_services["migrate"]["command"][:2] == ["control-plane", "migrate"]
    assert compact_services["taxonomy"]["command"][:2] == ["control-plane", "taxonomy"]
    assert compact_services["migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert compact_services["taxonomy"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert compact_services["airmux"]["depends_on"]["taxonomy"]["condition"] == "service_completed_successfully"

    services = split["services"]
    assert "setup" not in services
    for name in ("control-plane", "data-plane-1", "data-plane-2", "console"):
        assert services[name]["image"] == "${AIRMUX_IMAGE:-airmux:local}"
        assert "build" not in services[name]
    for name in ("migrate", "taxonomy"):
        assert services[name]["extends"] == {"file": "docker-compose.yml", "service": name}
    assert services["control-plane"]["command"] == "control-plane"
    assert services["data-plane-1"]["command"] == "data-plane"
    assert services["data-plane-2"]["command"] == "data-plane"
    assert services["console"]["command"] == "console"
    assert services["control-plane"]["depends_on"]["taxonomy"]["condition"] == "service_completed_successfully"
    for name in ("data-plane-1", "data-plane-2"):
        assert services[name]["depends_on"]["control-plane"]["condition"] == "service_healthy"

    combined = compact_text + split_text
    assert not any(variable in combined for variable in ROLE_IMAGE_VARIABLES)
    assert "target:" not in combined


def test_ci_builds_the_image_once_before_exercising_both_topologies() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/main-ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["docker"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])

    assert commands.count("docker build ") == 1
    assert "docker-compose.yml" in commands
    assert "docker-compose.split.yml" in commands
    assert "docker compose" in commands
    assert not re.search(r"docker compose .* --build", commands)
    assert "docker image save " not in commands


def test_main_ci_dispatch_uploads_the_release_image_reference() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/main-ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["docker"]["steps"]
    publish = next(step for step in steps if step.get("name") == "Publish the validated main image")
    upload = next(step for step in steps if step.get("name") == "Upload the validated image reference")

    assert publish["if"] == "github.ref == 'refs/heads/main'"
    assert upload["if"] == publish["if"]


def test_main_ci_publishes_the_image_it_built() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/main-ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["docker"]["steps"]
    build = next(step for step in steps if step.get("name") == "Build the candidate image once")
    publish = next(step for step in steps if step.get("name") == "Publish the validated main image")

    assert 'echo "image-id=$image_id" >> "$GITHUB_OUTPUT"' in build["run"]
    assert 'test "$(docker image inspect "$AIRMUX_IMAGE" --format \'{{.Id}}\')" = "${{ steps.image.outputs.image-id }}"' in publish["run"]
