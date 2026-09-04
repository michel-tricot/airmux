from __future__ import annotations

import tomllib
from pathlib import Path

import yaml


def test_runtime_image_drops_root_privileges():
    dockerfile = Path(__file__).resolve().parents[4] / "Dockerfile"
    assert "USER 10001:10001" in dockerfile.read_text(encoding="utf-8")


def test_runtime_image_installs_backend_dependency_group():
    root = Path(__file__).resolve().parents[4]
    dockerfile = root / "Dockerfile"
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    content = dockerfile.read_text(encoding="utf-8")
    assert set(project["dependency-groups"]["backend"]) == {"cli", "control-plane", "data-plane"}
    assert content.count("uv sync --only-group backend --frozen") == 2
    assert "--no-install-package" not in content


def test_default_deployment_is_one_application_and_postgres():
    root = Path(__file__).resolve().parents[4]
    services = yaml.safe_load((root / "docker-compose.yml").read_text())["services"]
    assert set(services) == {"airllm", "postgres"}
    assert services["airllm"]["build"]["target"] == "all-in-one"


def test_split_gateways_have_independent_state_and_shared_provider_environment():
    root = Path(__file__).resolve().parents[4]
    services = yaml.safe_load((root / "docker-compose.split.yml").read_text())["services"]
    first = services["data-plane-1"]
    second = services["data-plane-2"]
    assert "gateway-1:/state/data-plane" in first["volumes"]
    assert "gateway-2:/state/data-plane" in second["volumes"]
    assert first["env_file"] == second["env_file"] == services["control-plane"]["env_file"]
    assert {name for name, service in services.items() if service.get("ports")} == {"console"}
    assert "provider-secrets:/state/secrets:ro" in first["volumes"]
    assert "provider-secrets:/state/secrets:ro" in second["volumes"]
    assert "DATABASE_URL" not in first.get("environment", {})
    assert "DATABASE_URL" not in second.get("environment", {})
