from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
ROLE_IMAGE_VARIABLES = ("AIRMUX_CONTROL_PLANE_IMAGE", "AIRMUX_DATA_PLANE_IMAGE", "AIRMUX_CONSOLE_IMAGE")
ROLES = {"setup", "control-plane", "data-plane", "console", "airmux"}


def test_dockerfile_builds_one_role_based_image() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    stages = re.findall(r"^FROM .+ AS ([a-z0-9-]+)$", dockerfile, re.MULTILINE)

    assert not ROLES.intersection(stages)
    assert "gosu" not in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'ENTRYPOINT ["/usr/bin/tini", "--", "/app/deploy/docker/start.sh"]' in dockerfile
    assert 'CMD ["airmux"]' in dockerfile
    assert not (ROOT / "deploy/docker/entrypoint.sh").exists()


def test_compose_topologies_project_the_same_image_into_roles() -> None:
    compact_text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    split_text = (ROOT / "docker-compose.split.yml").read_text(encoding="utf-8")
    compact = yaml.safe_load(compact_text)
    split = yaml.safe_load(split_text)

    assert "build" not in compact["services"]["airmux"]
    assert compact["services"]["airmux"]["image"] == "${AIRMUX_IMAGE:-airmux:local}"
    assert compact["services"]["airmux"]["command"] == "airmux"

    services = split["services"]
    for name in ("setup", "control-plane", "data-plane-1", "data-plane-2", "console"):
        assert services[name]["image"] == "${AIRMUX_IMAGE:-airmux:local}"
        assert "build" not in services[name]
    assert services["setup"]["command"] == "setup"
    assert services["control-plane"]["command"] == "control-plane"
    assert services["data-plane-1"]["command"] == "data-plane"
    assert services["data-plane-2"]["command"] == "data-plane"
    assert services["console"]["command"] == "console"
    assert services["setup"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    for name in ("control-plane", "data-plane-1", "data-plane-2"):
        assert services[name]["depends_on"]["setup"]["condition"] == "service_completed_successfully"

    combined = compact_text + split_text
    assert not any(variable in combined for variable in ROLE_IMAGE_VARIABLES)
    assert "target:" not in combined


def test_container_start_script_accepts_only_the_documented_roles() -> None:
    script = (ROOT / "deploy/docker/start.sh").read_text(encoding="utf-8")

    assert set(re.findall(r"^  ([a-z][a-z-]+)\)$", script, re.MULTILINE)) == ROLES
    assert "Expected airmux, console, control-plane, data-plane, or setup" in script
    assert "/state" not in script


def test_ci_builds_the_image_once_before_exercising_both_topologies() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["docker"]
    commands = "\n".join(step.get("run", "") for step in job["steps"])

    assert commands.count("docker build ") == 1
    assert "docker-compose.yml" in commands
    assert "docker-compose.split.yml" in commands
    assert "docker compose" in commands
    assert not re.search(r"docker compose .* --build", commands)
    assert commands.count("docker image save ") == 1
