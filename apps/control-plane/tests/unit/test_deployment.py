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


def test_gateway_replicas_have_independent_persistent_state():
    root = Path(__file__).resolve().parents[4]
    config = yaml.safe_load((root / "deploy/distributed/compose.yml").read_text())
    services = config["services"]
    first = services["data-plane-1"]
    second = services["data-plane-2"]
    assert "gateway-1:/state/data-plane" in first["volumes"]
    assert "gateway-2:/state/data-plane" in second["volumes"]
    assert first["environment"]["GW_DATAPLANE_TOKEN"] == second["environment"]["GW_DATAPLANE_TOKEN"]
    assert "DATABASE_URL" not in first["environment"]
    assert "DATABASE_URL" not in second["environment"]


def test_split_layout_keeps_credentials_read_only_and_backends_private():
    root = Path(__file__).resolve().parents[4]
    services = yaml.safe_load((root / "docker-compose.yml").read_text())["services"]
    assert {name for name, service in services.items() if service.get("ports")} == {"console"}
    assert "runtime-credentials:/state/runtime:ro" in services["control-plane"]["volumes"]
    assert "runtime-credentials:/state/runtime:ro" in services["data-plane"]["volumes"]
    assert "provider-secrets:/state/secrets:ro" in services["data-plane"]["volumes"]
    assert "gateway-state:/state/data-plane" in services["data-plane"]["volumes"]
    assert not any("gateway-state" in mount for mount in services["control-plane"]["volumes"])
    assert all(not service.get("profiles") for service in services.values())
